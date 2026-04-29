"""Tools: Degiro portfolio / search / quote / candles / indicators / chart / orders.

Read tools are always exposed when Degiro credentials are set. The three
order tools (`degiro_propose_order`, `degiro_list_open_orders`,
`degiro_propose_cancel`) are gated by `cfg.degiro_orders_enabled` and rely on
the human-in-the-loop flow described in `docs/fonctionnel/ordres-degiro.md`:
the LLM proposes a row in `pending_actions`, only a Telegram inline-button
callback executes the order against Degiro.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from agent import degiro, indicators, orders, telegram as telegram_dispatch
from agent.config import cfg
from agent.tools import register

logger = logging.getLogger(__name__)


def _fmt_price(value: float | None, currency: str | None = None) -> str:
    if value is None:
        return "n/a"
    base = f"{value:.2f}"
    return f"{base} {currency}" if currency else base


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


@dataclass
class CloseSeries:
    closes: list[float]
    last_bar_ts: str
    is_provisional: bool


def _latest_intraday_close(
    vwd_id: str, vwd_identifier_type: str | None
) -> tuple[float | None, str | None]:
    """Return (close, ts_iso) of the most recent 10-minute intraday tick, or
    (None, None) if intraday data isn't available."""
    try:
        rows = degiro.load_candles(
            vwd_id,
            "today-10m",
            vwd_identifier_type=vwd_identifier_type,
        )
    except Exception as exc:
        logger.warning("intraday fetch failed for vwd_id=%s: %s", vwd_id, exc)
        return None, None
    if not rows:
        return None, None
    return rows[-1].close, rows[-1].ts


def build_close_series(
    rows: list[degiro.CandleRow],
    *,
    vwd_id: str,
    vwd_identifier_type: str | None,
    currency: str | None,
    now: datetime | None = None,
) -> CloseSeries:
    """Build a chronological close series from cached daily rows. If the latest
    cached bar is older than today (or today's bar isn't settled yet), graft
    the most recent intraday close as a provisional last point so the
    indicators reflect the live market view at any hour of day. The `now`
    argument is only used by tests."""
    closes = [r.close for r in rows]
    if not rows:
        return CloseSeries(closes=closes, last_bar_ts="", is_provisional=False)

    last_ts_iso = rows[-1].ts
    last_dt = datetime.fromisoformat(last_ts_iso.replace("Z", "+00:00"))
    paris_now = (now or datetime.now(degiro.PARIS_TZ)).astimezone(degiro.PARIS_TZ)
    today_paris = paris_now.date()
    last_is_today = last_dt.astimezone(degiro.PARIS_TZ).date() == today_paris
    settled = degiro.is_today_bar_settled(currency, now=paris_now)

    if last_is_today and settled:
        return CloseSeries(closes=closes, last_bar_ts=last_ts_iso, is_provisional=False)

    intraday_close, intraday_ts = _latest_intraday_close(vwd_id, vwd_identifier_type)
    if intraday_close is None:
        # No intraday data available — return cached series as-is, but flag it
        # provisional if today's bar is in cache without settle confirmation.
        return CloseSeries(
            closes=closes,
            last_bar_ts=last_ts_iso,
            is_provisional=last_is_today and not settled,
        )

    if last_is_today:
        closes[-1] = intraday_close
    else:
        closes.append(intraday_close)
    return CloseSeries(
        closes=closes,
        last_bar_ts=intraday_ts or last_ts_iso,
        is_provisional=True,
    )


def _fmt_ts(iso: str | None) -> str:
    if not iso:
        return "n/a"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


# ---------------------------------------------------------------------------
# degiro_portfolio
# ---------------------------------------------------------------------------

CASH_PSEUDO_PRODUCTS = {"FLATEX_EUR", "FLATEX_CASH"}


@register(
    name="degiro_portfolio",
    description=(
        "Snapshot of the Degiro portfolio: positions (size, avg price, "
        "current price, market value, P&L day and cumulative), cash balances "
        "by currency. Read-only — no orders."
    ),
    parameters={
        "type": "object",
        "properties": {
            "include_closed": {
                "type": "boolean",
                "description": "Include closed positions (size = 0). Default: false.",
            },
        },
        "required": [],
    },
)
def degiro_portfolio(include_closed: bool = False) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured. Set degiro_username / degiro_password."

    client = degiro.get_client()
    positions = client.get_portfolio(only_open=not include_closed)
    cash = client.get_cash()

    trading_positions = []
    cash_positions = []
    for pos in positions:
        symbol = pos.symbol or pos.name or pos.product_id
        if symbol and symbol.upper() in CASH_PSEUDO_PRODUCTS:
            cash_positions.append(pos)
        else:
            trading_positions.append(pos)

    total_value = sum(p.market_value or 0 for p in trading_positions)
    total_pl = sum(p.pl_base or 0 for p in trading_positions if p.pl_base is not None)
    total_today_pl = sum(
        p.today_pl_base or 0 for p in trading_positions if p.today_pl_base is not None
    )

    lines = ["Degiro portfolio"]
    lines.append(f"- Positions: {len(trading_positions)}")
    lines.append(f"- Market value: {total_value:,.2f}")
    lines.append(f"- P&L cumulative: {total_pl:+,.2f}")
    lines.append(f"- P&L today: {total_today_pl:+,.2f}")
    if cash:
        cash_str = ", ".join(f"{v:,.2f} {c}" for c, v in sorted(cash.items()))
        lines.append(f"- Cash: {cash_str}")
    if cash_positions:
        pseudo = ", ".join(
            f"{(p.symbol or p.name or p.product_id)} {p.market_value:+,.2f}"
            for p in cash_positions
        )
        lines.append(f"- Cash pseudo-products: {pseudo}")

    lines.append("")
    lines.append("Holdings:")
    if not trading_positions:
        lines.append("- (none)")
    else:
        by_value = sorted(
            trading_positions, key=lambda p: p.market_value or 0, reverse=True
        )
        for p in by_value:
            weight = (p.market_value / total_value * 100) if total_value else 0
            change = None
            if p.avg_price and p.current_price:
                change = ((p.current_price / p.avg_price) - 1.0) * 100
            bits = [
                f"{(p.symbol or p.isin or p.product_id)} ({p.name or '-'})",
                f"size {p.size:g}",
                f"px {_fmt_price(p.current_price, p.currency)}",
                f"value {p.market_value:,.2f}",
                f"w {weight:.1f}%",
                f"vs avg {_fmt_pct(change)}",
            ]
            if p.today_pl_base is not None:
                bits.append(f"day {p.today_pl_base:+,.2f}")
            lines.append("- " + " | ".join(bits))

    lines.append("")
    lines.append("Read-only: the agent cannot place, check, confirm or cancel orders.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# degiro_search
# ---------------------------------------------------------------------------


@register(
    name="degiro_search",
    description=(
        "Search Degiro's product catalog by name, symbol or ISIN. Returns a short "
        "list of candidates with ISIN, symbol, exchange id and currency. Use it "
        "when you do not know the exact ISIN before calling degiro_quote / "
        "degiro_candles / degiro_indicators."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free text, ticker or ISIN."},
            "limit": {
                "type": "integer",
                "description": "Max candidates to return. Default 5.",
            },
        },
        "required": ["query"],
    },
)
def degiro_search(query: str, limit: int = 5) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    client = degiro.get_client()
    results = client.search_products(query, limit=max(limit, 1))
    if not results:
        return f"No product found for {query!r}."
    lines = [f"Degiro search: {query!r} ({len(results)} result(s))"]
    for p in results[:limit]:
        bits = [
            p.symbol or "-",
            p.isin or "-",
            f"ccy={p.currency or '-'}",
            p.name or "",
        ]
        lines.append("- " + " | ".join(bits))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# degiro_quote
# ---------------------------------------------------------------------------


@register(
    name="degiro_quote",
    description=(
        "Current price of a security via Degiro: last price, day change vs "
        "previous close, drawdown vs 52-week high, distance to 52-week low, "
        "currency and last tick time (UTC)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "ISIN (preferred), symbol or name.",
            },
        },
        "required": ["query"],
    },
)
def degiro_quote(query: str) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    ref = degiro.resolve_product(query)
    if not ref.vwd_id:
        return f"Error: no vwdId for {query!r} — price feed unavailable."
    if not ref.metadata_ok:
        return f"Error: no metadata for {query!r} — product not tradable via charting."

    client = degiro.get_client()
    meta = client.price_metadata(ref.vwd_id, ref.vwd_identifier_type)
    last = meta.get("lastPrice")
    prev = meta.get("previousClosePrice")
    currency = meta.get("currency") or ref.currency
    high_1y = meta.get("highPriceP1Y")
    low_1y = meta.get("lowPriceP1Y")
    last_time = meta.get("lastTime")

    day_change = None
    if last is not None and prev:
        day_change = ((last / prev) - 1.0) * 100
    dd_52w = indicators.drawdown_from_high(last, high_1y)
    up_from_low = None
    if last is not None and low_1y:
        up_from_low = ((last / low_1y) - 1.0) * 100

    label = ref.symbol or ref.isin or query
    parts = [
        f"{label} ({ref.name or '-'})",
        f"last {_fmt_price(last, currency)}",
        f"day {_fmt_pct(day_change)}",
        f"52w high {_fmt_price(high_1y)} (dd {_fmt_pct(dd_52w)})",
        f"52w low {_fmt_price(low_1y)} (up {_fmt_pct(up_from_low)})",
        f"ts {_fmt_ts(last_time if last_time and 'T' not in last_time else last_time)}",
    ]
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# degiro_candles
# ---------------------------------------------------------------------------

MAX_CANDLES_PRINTED = 20


@register(
    name="degiro_candles",
    description=(
        "Close-only price history for a security on a named window. Supported "
        "windows: today-10m (P1D/PT10M), 5d-1h (P5D/PT1H), 1m-1d (P1M/P1D), "
        "3m-1d (P3M/P1D), 1y-1d (P1Y/P1D, default), 5y-1w (P5Y/P7D). "
        "Degiro returns CLOSE ONLY — no open/high/low/volume."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "ISIN (preferred), symbol or name.",
            },
            "window": {
                "type": "string",
                "description": "Window name. Default '1y-1d'.",
                "enum": list(degiro.WINDOW_MAP.keys()),
            },
            "limit": {
                "type": "integer",
                "description": f"Max candles to display. Default {MAX_CANDLES_PRINTED}.",
            },
        },
        "required": ["query"],
    },
)
def degiro_candles(
    query: str, window: str = "1y-1d", limit: int = MAX_CANDLES_PRINTED
) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    ref = degiro.resolve_product(query)
    if not ref.vwd_id:
        return f"Error: no vwdId for {query!r}."
    if not ref.history_ok:
        return f"Error: no usable price history for {query!r}."

    rows = degiro.load_candles(
        ref.vwd_id,
        window,
        vwd_identifier_type=ref.vwd_identifier_type,
        currency=ref.currency,
    )
    if not rows:
        return f"No candles returned for {query!r} on window {window}."

    period, resolution = degiro.window_to_period_resolution(window)
    lines = [
        f"{ref.symbol or ref.isin or query} — {ref.name or '-'}",
        f"window={window} (period={period}, resolution={resolution}) — {len(rows)} candles, close-only",
    ]
    for row in rows[-limit:]:
        lines.append(f"- {row.ts} close={row.close:.4f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# degiro_indicators
# ---------------------------------------------------------------------------


@register(
    name="degiro_indicators",
    description=(
        "Structured verdict for a rebound or swing setup on a single security, "
        "computed close-only (Degiro does not expose OHLV). Fetches ~1y of daily "
        "closes and, for swing, requires ≥210 closes (SMA200). Outside market "
        "hours and on intra-session calls, the latest intraday tick is grafted "
        "as a provisional last bar so the verdict reflects the live view. "
        "Returns a signal (candidate / recovery / neutral / reject), score, "
        "reasons, raw metrics and a freshness flag (bar_ts + provisional)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "strategy": {
                "type": "string",
                "enum": ["rebound", "swing"],
            },
        },
        "required": ["query", "strategy"],
    },
)
def degiro_indicators(query: str, strategy: str) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    if strategy not in ("rebound", "swing"):
        return "Error: strategy must be 'rebound' or 'swing'."

    ref = degiro.resolve_product(query)
    if not ref.vwd_id:
        return f"Error: no vwdId for {query!r}."
    if not ref.history_ok:
        return (
            f"Error: no usable price history for {query!r} — "
            "indicators require a valid close series."
        )

    rows = degiro.load_candles(
        ref.vwd_id,
        "1y-1d",
        vwd_identifier_type=ref.vwd_identifier_type,
        currency=ref.currency,
    )
    series = build_close_series(
        rows,
        vwd_id=ref.vwd_id,
        vwd_identifier_type=ref.vwd_identifier_type,
        currency=ref.currency,
    )

    high_52w: float | None = None
    if ref.metadata_ok:
        try:
            meta = degiro.get_client().price_metadata(
                ref.vwd_id, ref.vwd_identifier_type
            )
            high_52w = meta.get("highPriceP1Y")
        except Exception as exc:
            logger.warning("metadata fetch failed during indicators: %s", exc)

    verdict = indicators.evaluate(strategy, series.closes, high_52w=high_52w)

    label = ref.symbol or ref.isin or query
    lines = [
        f"{label} — strategy={strategy} signal={verdict.signal} score={verdict.score}",
        f"bar_ts={series.last_bar_ts} provisional={series.is_provisional}",
    ]
    for reason in verdict.reasons:
        lines.append(f"- {reason}")
    metric_bits = []
    for name, val in verdict.metrics.items():
        if val is None:
            metric_bits.append(f"{name}=n/a")
        else:
            metric_bits.append(f"{name}={val:.3f}")
    if metric_bits:
        lines.append("metrics: " + ", ".join(metric_bits))
    lines.append(
        "Note: Degiro does not expose OHLV — volume-based confirmations are unavailable."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# degiro_chart
# ---------------------------------------------------------------------------

CHART_MAX_POINTS = 250
QUICKCHART_CREATE_URL = "https://quickchart.io/chart/create"


def _downsample_for_chart(xs: list, max_points: int = CHART_MAX_POINTS) -> list:
    n = len(xs)
    if n <= max_points:
        return list(xs)
    return [xs[round(i * (n - 1) / (max_points - 1))] for i in range(max_points)]


def _format_chart_label(ts_iso: str, window: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).astimezone(degiro.PARIS_TZ)
    except ValueError:
        return ts_iso
    if window in ("today-10m", "5d-1h"):
        return dt.strftime("%d/%m %H:%M")
    if window == "5y-1w":
        return dt.strftime("%m/%y")
    return dt.strftime("%d/%m")


def _build_chart_config(title: str, labels: list[str], closes: list[float]) -> dict:
    going_up = closes[-1] >= closes[0]
    border = "rgb(34,197,94)" if going_up else "rgb(239,68,68)"
    bg = "rgba(34,197,94,0.15)" if going_up else "rgba(239,68,68,0.15)"
    return {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": title,
                "data": closes,
                "borderColor": border,
                "backgroundColor": bg,
                "fill": True,
                "pointRadius": 0,
                "borderWidth": 2,
                "tension": 0.25,
            }],
        },
        "options": {
            "plugins": {
                "title": {"display": True, "text": title, "font": {"size": 16}},
                "legend": {"display": False},
            },
            "scales": {
                "y": {"grid": {"color": "rgba(0,0,0,0.05)"}},
                "x": {"grid": {"display": False}, "ticks": {"maxTicksLimit": 8}},
            },
        },
    }


async def _quickchart_url(cfg_dict: dict) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            QUICKCHART_CREATE_URL,
            json={"chart": cfg_dict, "version": "4"},
        )
        resp.raise_for_status()
        body = resp.json()
    if not body.get("success") or not body.get("url"):
        raise RuntimeError(f"QuickChart did not return a URL: {body!r}")
    return body["url"]


@register(
    name="degiro_chart",
    description=(
        "Generate a PNG line chart of the close-only price series for a "
        "security on a named window, and send it directly to the user's "
        "Telegram chat as a photo. Use when the user asks for a graph / "
        "chart / visual, or when illustrating a market-watch candidate or "
        "a portfolio line. Windows: today-10m, 5d-1h, 1m-1d, 3m-1d, "
        "1y-1d, 5y-1w. Returns a short status string; the image arrives "
        "out-of-band via Telegram."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "ISIN (preferred), symbol or name.",
            },
            "window": {
                "type": "string",
                "description": "Window name. Default '1y-1d'.",
                "enum": list(degiro.WINDOW_MAP.keys()),
            },
        },
        "required": ["query"],
    },
)
async def degiro_chart(
    query: str,
    window: str = "1y-1d",
    _context: dict | None = None,
) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    chat_id = (_context or {}).get("chat_id")
    if chat_id is None:
        return "Error: chart can only be sent in a Telegram chat context."

    ref = degiro.resolve_product(query)
    if not ref.vwd_id:
        return f"Error: no vwdId for {query!r}."
    if not ref.history_ok:
        return f"Error: no usable price history for {query!r}."

    rows = degiro.load_candles(
        ref.vwd_id,
        window,
        vwd_identifier_type=ref.vwd_identifier_type,
        currency=ref.currency,
    )
    if not rows:
        return f"No candles returned for {query!r} on window {window}."

    series = build_close_series(
        rows,
        vwd_id=ref.vwd_id,
        vwd_identifier_type=ref.vwd_identifier_type,
        currency=ref.currency,
    )
    raw_labels = [_format_chart_label(r.ts, window) for r in rows]
    # build_close_series may append an extra intraday point; mirror it on labels
    if len(series.closes) > len(raw_labels):
        raw_labels.append(_format_chart_label(series.last_bar_ts, window))

    closes = _downsample_for_chart(series.closes)
    labels = _downsample_for_chart(raw_labels)

    display_name = ref.name or ref.symbol or ref.isin or query
    title = f"{display_name} — {window}"
    caption = f"{display_name} — {window} ({len(closes)} pts, close-only)"
    label = ref.symbol or ref.isin or query

    cfg_dict = _build_chart_config(title, labels, closes)
    try:
        url = await _quickchart_url(cfg_dict)
    except Exception as exc:
        logger.exception("QuickChart render failed for %s/%s", query, window)
        return f"Error: failed to render chart ({exc.__class__.__name__})."

    try:
        await telegram_dispatch.send_photo(int(chat_id), url, caption=caption)
    except Exception as exc:
        logger.exception("Failed to send chart to Telegram chat_id=%s", chat_id)
        return f"Error: chart rendered but Telegram send failed ({exc.__class__.__name__}). URL: {url}"

    return f"Graphique envoye: {label} sur {window} ({len(closes)} points)."


# ---------------------------------------------------------------------------
# Order tools (gated by cfg.degiro_orders_enabled).
# Execution never happens here: these tools only insert a pending_actions row
# and ask Telegram to display the inline ✅/❌ confirmation. The actual call
# to Degiro is made by `agent.telegram.handle_order_callback` after the user
# clicks ✅.
# ---------------------------------------------------------------------------


def _resolve_product_names(product_ids: list[str]) -> dict[str, str]:
    ids = sorted({pid for pid in product_ids if pid})
    if not ids:
        return {}
    try:
        products = degiro.get_client().get_products_by_ids(ids)
    except Exception as exc:
        logger.warning("get_products_by_ids failed: %s", exc)
        return {}
    return {pid: (p.name or p.symbol or pid) for pid, p in products.items()}


def _label_open_order(o, names: dict[str, str] | None = None) -> str:
    name = (names or {}).get(o.product_id) or o.product_id
    side = (o.buy_sell or "").upper()
    price = f"{o.price:.4f}" if o.price is not None else "n/a"
    return f"{side} {o.size:g} {name} @ {price}"


async def degiro_propose_order(
    query: str,
    side: str,
    size: float,
    limit_price: float,
    _context: dict | None = None,
) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    if not cfg.degiro_orders_enabled:
        return "Error: degiro_orders_enabled est false. Activez le kill switch en configuration."
    chat_id = (_context or {}).get("chat_id")
    if chat_id is None:
        return "Error: ce tool ne peut etre appele que depuis un chat Telegram."

    try:
        ref = await asyncio.to_thread(degiro.resolve_product, query)
    except Exception as exc:
        return f"Error: produit introuvable pour {query!r} ({exc})."
    if not ref.product_id:
        return f"Error: pas de productId Degiro pour {query!r}."

    label = ref.symbol or ref.isin or ref.name or query
    try:
        pending_id, preview = await asyncio.to_thread(
            orders.create_pending_place,
            chat_id=int(chat_id),
            product_id=str(ref.product_id),
            isin=ref.isin,
            label=label,
            side=side,
            size=float(size),
            limit_price=float(limit_price),
            currency=ref.currency,
        )
    except orders.OrderGuardError as exc:
        return f"Refus garde-fou : {exc}"
    except Exception as exc:
        logger.exception("create_pending_place failed")
        return f"Error: insertion pending_actions echouee ({exc})."

    try:
        await telegram_dispatch.send_order_confirmation(int(chat_id), pending_id, preview)
    except Exception as exc:
        logger.exception("send_order_confirmation failed pending_id=%s", pending_id)
        return f"Error: pending #{pending_id} insere mais envoi Telegram echoue ({exc})."

    return (
        f"Demande #{pending_id} envoyee sur Telegram. "
        f"Expire dans {orders.TTL_MINUTES} min. La confirmation se fait via les "
        "boutons du message; je n'attends pas de reponse."
    )


async def degiro_list_open_orders() -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    try:
        open_orders = await asyncio.to_thread(degiro.list_open_orders)
    except Exception as exc:
        logger.exception("list_open_orders failed")
        return f"Error: lecture des ordres echouee ({exc})."
    if not open_orders:
        return "Aucun ordre ouvert."
    names = await asyncio.to_thread(
        _resolve_product_names, [o.product_id for o in open_orders]
    )
    lines = ["Ordres ouverts:"]
    for o in open_orders:
        lines.append(f"- {_label_open_order(o, names)} (orderId={o.order_id})")
    return "\n".join(lines)


async def degiro_propose_cancel(
    order_id: str,
    _context: dict | None = None,
) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured."
    if not cfg.degiro_orders_enabled:
        return "Error: degiro_orders_enabled est false."
    chat_id = (_context or {}).get("chat_id")
    if chat_id is None:
        return "Error: ce tool ne peut etre appele que depuis un chat Telegram."

    try:
        open_orders = await asyncio.to_thread(degiro.list_open_orders)
    except Exception as exc:
        return f"Error: lecture des ordres echouee ({exc})."
    target = next((o for o in open_orders if str(o.order_id) == str(order_id)), None)
    if target is None:
        return f"Error: orderId {order_id!r} introuvable parmi les ordres ouverts."

    names = await asyncio.to_thread(_resolve_product_names, [target.product_id])
    label = _label_open_order(target, names)
    try:
        pending_id, preview = await asyncio.to_thread(
            orders.create_pending_cancel,
            chat_id=int(chat_id),
            order_id=str(order_id),
            label=label,
        )
    except orders.OrderGuardError as exc:
        return f"Refus garde-fou : {exc}"
    except Exception as exc:
        logger.exception("create_pending_cancel failed")
        return f"Error: insertion pending_actions echouee ({exc})."

    try:
        await telegram_dispatch.send_order_confirmation(int(chat_id), pending_id, preview)
    except Exception as exc:
        logger.exception("send_order_confirmation failed pending_id=%s", pending_id)
        return f"Error: pending #{pending_id} insere mais envoi Telegram echoue ({exc})."

    return (
        f"Demande d'annulation #{pending_id} envoyee. "
        f"Expire dans {orders.TTL_MINUTES} min."
    )


if cfg.degiro_orders_enabled:
    register(
        name="degiro_propose_order",
        description=(
            "Propose un ordre d'achat ou de vente sur Degiro. N'execute RIEN : "
            "la fonction insere une ligne pending_actions et envoie un message "
            "Telegram avec deux boutons (Confirmer / Annuler). Seul le clic sur "
            "Confirmer passe l'ordre. Type d'ordre fixe a LIMIT, validite GTC "
            "(continu). Garde-fous : kill switch global, plafond 1500 EUR par "
            "BUY, quota 4 BUY confirmes par fenetre glissante de 24h, TTL "
            "pending de 5 min."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "ISIN (preferred), symbol or name to resolve via Degiro.",
                },
                "side": {
                    "type": "string",
                    "enum": ["BUY", "SELL"],
                    "description": "BUY ou SELL.",
                },
                "size": {
                    "type": "number",
                    "description": "Quantite (nombre d'actions).",
                },
                "limit_price": {
                    "type": "number",
                    "description": "Prix limite par action.",
                },
            },
            "required": ["query", "side", "size", "limit_price"],
        },
    )(degiro_propose_order)

    register(
        name="degiro_list_open_orders",
        description=(
            "Liste les ordres ouverts (non encore executes ni annules) sur "
            "Degiro. Lecture seule. Renvoie pour chaque ordre : orderId, sens, "
            "taille, prix limite, productId."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
    )(degiro_list_open_orders)

    register(
        name="degiro_propose_cancel",
        description=(
            "Propose l'annulation d'un ordre Degiro ouvert (par orderId). "
            "Comme degiro_propose_order, l'annulation n'est PAS effectuee ici : "
            "un message Telegram avec boutons Confirmer/Annuler est envoye, et "
            "seul le clic Confirmer transmet la cancellation a Degiro."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Identifiant Degiro de l'ordre a annuler (cf. degiro_list_open_orders).",
                },
            },
            "required": ["order_id"],
        },
    )(degiro_propose_cancel)

"""Tools: Degiro portfolio / search / quote / candles / indicators.

All tools are READ-ONLY by construction — the vendored degiro_client copy
has no order-placement methods (see my-agent/vendor/degiro_client/VENDORED.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from agent import degiro, indicators
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

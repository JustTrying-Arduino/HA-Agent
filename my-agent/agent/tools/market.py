"""Tool: end-of-day market watch with Marketstack-backed caching."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

from agent.config import cfg
from agent.db import commit, fetchall, fetchone, get_db
from agent.tools import register

logger = logging.getLogger(__name__)

MARKETSTACK_BASE_URL = "https://api.marketstack.com/v2"
WATCHLIST_PATH = Path("skills") / "market-watch" / "watchlist.json"
DEFAULT_GROUP = "core_daily"
DEFAULT_HISTORY_DAYS = 120
MIN_BARS_FOR_ANALYSIS = 25
DEFAULT_MAX_MOVERS = 6
DEFAULT_MAX_CANDIDATES = 5
DEFAULT_MIN_DROP_PCT = 4.0
DEFAULT_MIN_DRAWNDOWN_PCT = 10.0
DEFAULT_MONTHLY_BUDGET = 80


@dataclass(frozen=True)
class WatchlistEntry:
    symbol: str
    exchange: str
    name: str


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _today_utc() -> date:
    return _now_utc().date()


def _recent_trading_day(ref: date | None = None) -> date:
    current = ref or _today_utc()
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base in (None, 0):
        return None
    return ((current / base) - 1.0) * 100.0


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _watchlist_abspath() -> Path:
    return Path(cfg.workspace_path) / WATCHLIST_PATH


def _load_watchlist_config() -> dict:
    path = _watchlist_abspath()
    if not path.exists():
        raise FileNotFoundError(
            f"Watchlist file not found: {path}. Create it from the workspace skill template."
        )
    return json.loads(path.read_text())


def _available_groups(config: dict) -> list[str]:
    groups = config.get("groups", {})
    return sorted(groups.keys())


def _resolve_watchlist(group: str | None) -> tuple[str, list[WatchlistEntry], dict]:
    config = _load_watchlist_config()
    groups = config.get("groups", {})
    target_group = group or config.get("default_group") or DEFAULT_GROUP
    if target_group == "all":
        names = list(groups.keys())
        raw_entries: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for name in names:
            for item in groups.get(name, []):
                key = (item["symbol"], item["exchange"])
                if key in seen:
                    continue
                seen.add(key)
                raw_entries.append(item)
    else:
        raw_entries = groups.get(target_group, [])
        if not raw_entries:
            available = ", ".join(_available_groups(config)) or "(none)"
            raise ValueError(
                f"Unknown or empty market watch group '{target_group}'. Available groups: {available}"
            )

    entries = [
        WatchlistEntry(
            symbol=item["symbol"].upper().strip(),
            exchange=item["exchange"].upper().strip(),
            name=item.get("name", item["symbol"]).strip(),
        )
        for item in raw_entries
    ]
    return target_group, entries, config


def _symbol_month_usage() -> int:
    month_prefix = _now_utc().strftime("%Y-%m")
    row = fetchone(
        "SELECT COALESCE(SUM(symbols_count), 0) AS total FROM market_api_usage WHERE substr(timestamp, 1, 7) = ?",
        (month_prefix,),
    )
    return int(row["total"]) if row else 0


def _log_api_usage(
    *,
    endpoint: str,
    request_kind: str,
    exchange: str,
    symbols: list[str],
    status: str,
    row_count: int,
    note: str | None = None,
) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO market_api_usage(
            timestamp, endpoint, request_kind, exchange, symbols, symbols_count, status, row_count, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _now_utc().isoformat().replace("+00:00", "Z"),
            endpoint,
            request_kind,
            exchange,
            ",".join(symbols),
            len(symbols),
            status,
            row_count,
            note,
        ),
    )
    db.commit()


def _fetch_symbol_status(entry: WatchlistEntry, history_days: int) -> dict:
    history_from = (_today_utc() - timedelta(days=max(history_days * 2, 90))).isoformat()
    row = fetchone(
        """
        SELECT
            MAX(date) AS latest_date,
            MAX(fetched_at) AS latest_fetch,
            SUM(CASE WHEN date >= ? THEN 1 ELSE 0 END) AS recent_bars
        FROM market_eod_prices
        WHERE symbol = ? AND exchange = ?
        """,
        (history_from, entry.symbol, entry.exchange),
    )
    return {
        "latest_date": row["latest_date"] if row else None,
        "latest_fetch": row["latest_fetch"] if row else None,
        "recent_bars": int(row["recent_bars"] or 0) if row else 0,
    }


def _fetch_marketstack_rows(
    *,
    exchange: str,
    symbols: list[str],
    history_days: int,
    request_kind: str,
) -> list[dict]:
    if not cfg.marketstack_api_key:
        raise RuntimeError("MARKETSTACK_API_KEY is missing")

    params = {
        "access_key": cfg.marketstack_api_key,
        "symbols": ",".join(symbols),
        "exchange": exchange,
        "limit": 1000,
        "offset": 0,
        "sort": "ASC",
    }
    endpoint = "/eod/latest"
    if request_kind == "history":
        endpoint = "/eod"
        params["date_from"] = (_today_utc() - timedelta(days=max(history_days * 2, 120))).isoformat()
        params["date_to"] = _today_utc().isoformat()

    rows: list[dict] = []
    try:
        while True:
            response = requests.get(
                f"{MARKETSTACK_BASE_URL}{endpoint}",
                params=params,
                timeout=20,
                headers={"User-Agent": "MyAgent/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("data", [])
            rows.extend(batch)

            pagination = payload.get("pagination", {})
            count = int(pagination.get("count", len(batch) or 0))
            offset = int(pagination.get("offset", 0))
            total = int(pagination.get("total", len(batch) or 0))
            if not batch or offset + count >= total:
                break
            params["offset"] = offset + count

        _log_api_usage(
            endpoint=endpoint,
            request_kind=request_kind,
            exchange=exchange,
            symbols=symbols,
            status="ok",
            row_count=len(rows),
        )
        return rows
    except Exception as exc:
        _log_api_usage(
            endpoint=endpoint,
            request_kind=request_kind,
            exchange=exchange,
            symbols=symbols,
            status="error",
            row_count=0,
            note=str(exc),
        )
        raise


def _upsert_market_rows(rows: list[dict]) -> None:
    if not rows:
        return
    db = get_db()
    fetched_at = _now_utc().isoformat().replace("+00:00", "Z")
    payload = []
    for row in rows:
        raw_date = (row.get("date") or "")[:10]
        symbol = (row.get("symbol") or "").upper()
        exchange = (row.get("exchange") or row.get("exchange_code") or "").upper()
        if not raw_date or not symbol or not exchange:
            continue
        payload.append(
            (
                symbol,
                exchange,
                raw_date,
                row.get("name"),
                row.get("price_currency"),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume"),
                fetched_at,
            )
        )
    db.executemany(
        """
        INSERT INTO market_eod_prices(
            symbol, exchange, date, name, currency, open, high, low, close, volume, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, exchange, date) DO UPDATE SET
            name = excluded.name,
            currency = excluded.currency,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            fetched_at = excluded.fetched_at
        """,
        payload,
    )
    commit()


def _refresh_market_data(entries: list[WatchlistEntry], history_days: int, force_refresh: bool) -> dict:
    by_exchange: dict[str, list[WatchlistEntry]] = defaultdict(list)
    for entry in entries:
        by_exchange[entry.exchange].append(entry)

    recent_day = _recent_trading_day()
    summary = {
        "refreshed_symbols": [],
        "cache_only_symbols": [],
    }

    for exchange, exchange_entries in by_exchange.items():
        needs_history: list[WatchlistEntry] = []
        needs_latest: list[WatchlistEntry] = []
        cache_only: list[WatchlistEntry] = []

        for entry in exchange_entries:
            status = _fetch_symbol_status(entry, history_days)
            latest_date = status["latest_date"]
            latest_fetch = status["latest_fetch"]
            fetched_today = bool(latest_fetch and latest_fetch[:10] == _today_utc().isoformat())
            insufficient_history = status["recent_bars"] < MIN_BARS_FOR_ANALYSIS
            stale_latest = not latest_date or latest_date < recent_day.isoformat()

            if force_refresh or insufficient_history:
                needs_history.append(entry)
            elif stale_latest and not fetched_today:
                needs_latest.append(entry)
            else:
                cache_only.append(entry)

        if needs_history:
            history_rows = _fetch_marketstack_rows(
                exchange=exchange,
                symbols=[entry.symbol for entry in needs_history],
                history_days=history_days,
                request_kind="history",
            )
            _upsert_market_rows(history_rows)
            summary["refreshed_symbols"].extend(f"{entry.symbol}:{exchange}" for entry in needs_history)

        if needs_latest:
            latest_rows = _fetch_marketstack_rows(
                exchange=exchange,
                symbols=[entry.symbol for entry in needs_latest],
                history_days=history_days,
                request_kind="latest",
            )
            _upsert_market_rows(latest_rows)
            summary["refreshed_symbols"].extend(f"{entry.symbol}:{exchange}" for entry in needs_latest)

        summary["cache_only_symbols"].extend(f"{entry.symbol}:{exchange}" for entry in cache_only)

    return summary


def _load_series(entries: list[WatchlistEntry], history_days: int) -> dict[tuple[str, str], list[dict]]:
    series: dict[tuple[str, str], list[dict]] = defaultdict(list)
    date_from = (_today_utc() - timedelta(days=max(history_days * 2, 120))).isoformat()
    for entry in entries:
        rows = fetchall(
            """
            SELECT symbol, exchange, date, name, currency, open, high, low, close, volume
            FROM market_eod_prices
            WHERE symbol = ? AND exchange = ? AND date >= ?
            ORDER BY date ASC
            """,
            (entry.symbol, entry.exchange, date_from),
        )
        series[(entry.symbol, entry.exchange)] = [dict(row) for row in rows]
    return series


def _analyze_entry(entry: WatchlistEntry, bars: list[dict]) -> dict | None:
    if len(bars) < 2:
        return None

    latest = bars[-1]
    prev = bars[-2]
    last_5 = bars[-6] if len(bars) >= 6 else None
    last_20 = bars[-21] if len(bars) >= 21 else None
    closes_20 = [bar["close"] for bar in bars[-20:] if bar["close"] is not None]
    closes_60 = [bar["close"] for bar in bars[-60:] if bar["close"] is not None]
    volumes_20 = [bar["volume"] for bar in bars[-20:] if bar["volume"] not in (None, 0)]

    close = latest["close"]
    low = latest["low"]
    high = latest["high"]
    volume = latest["volume"]
    close_position = None
    if low is not None and high not in (None, low):
        close_position = (close - low) / (high - low)

    avg_volume_20 = _avg(volumes_20[:-1] or volumes_20)
    volume_ratio = (volume / avg_volume_20) if volume and avg_volume_20 not in (None, 0) else None
    ma20 = _avg(closes_20)
    drawdown_20 = _pct_change(close, max(closes_20) if closes_20 else None)
    drawdown_60 = _pct_change(close, max(closes_60) if closes_60 else None)
    distance_ma20 = _pct_change(close, ma20)
    recovery_from_low = _pct_change(close, low)
    change_1d = _pct_change(close, prev["close"])
    change_5d = _pct_change(close, last_5["close"] if last_5 else None)
    change_20d = _pct_change(close, last_20["close"] if last_20 else None)

    rebound_score = 0
    if change_1d is not None and change_1d <= -4:
        rebound_score += 1
    if change_5d is not None and change_5d <= -8:
        rebound_score += 1
    if drawdown_20 is not None and drawdown_20 <= -10:
        rebound_score += 1
    if recovery_from_low is not None and recovery_from_low >= 1:
        rebound_score += 1
    if volume_ratio is not None and volume_ratio >= 1.5:
        rebound_score += 1

    falling_knife_score = 0
    if change_1d is not None and change_1d <= -5:
        falling_knife_score += 1
    if close_position is not None and close_position <= 0.2:
        falling_knife_score += 1
    if recovery_from_low is not None and recovery_from_low < 0.5:
        falling_knife_score += 1
    if drawdown_20 is not None and drawdown_20 <= -15:
        falling_knife_score += 1

    strategies: list[str] = []
    if change_1d is not None and change_1d <= -4 and recovery_from_low is not None and recovery_from_low >= 1:
        strategies.append("capitulation rebound")
    if change_5d is not None and change_5d <= -8 and drawdown_20 is not None and drawdown_20 <= -10:
        strategies.append("oversold mean reversion")
    if distance_ma20 is not None and -6 <= distance_ma20 <= -2 and drawdown_60 is not None and drawdown_60 > -10:
        strategies.append("trend pullback")
    if change_1d is not None and change_1d >= 4 and close_position is not None and close_position >= 0.7:
        strategies.append("relative strength breakout")

    return {
        "symbol": entry.symbol,
        "exchange": entry.exchange,
        "name": latest.get("name") or entry.name,
        "currency": latest.get("currency"),
        "date": latest["date"],
        "close": close,
        "change_1d": change_1d,
        "change_5d": change_5d,
        "change_20d": change_20d,
        "drawdown_20": drawdown_20,
        "drawdown_60": drawdown_60,
        "distance_ma20": distance_ma20,
        "recovery_from_low": recovery_from_low,
        "close_position": close_position,
        "volume_ratio": volume_ratio,
        "rebound_score": rebound_score,
        "falling_knife_score": falling_knife_score,
        "strategies": strategies,
        "bars": len(bars),
    }


def _render_line(item: dict) -> str:
    extra = [
        f"close {_fmt_price(item['close'])}",
        f"1d {_fmt_pct(item['change_1d'])}",
        f"5d {_fmt_pct(item['change_5d'])}",
        f"dd20 {_fmt_pct(item['drawdown_20'])}",
    ]
    return f"- {item['symbol']} ({item['exchange']}) {item['name']} | " + ", ".join(extra)


def _render_candidate(item: dict) -> str:
    strategy_text = ", ".join(item["strategies"]) if item["strategies"] else "news-driven overreaction check"
    facts = [
        f"score {item['rebound_score']}",
        f"1d {_fmt_pct(item['change_1d'])}",
        f"dd20 {_fmt_pct(item['drawdown_20'])}",
    ]
    if item["recovery_from_low"] is not None:
        facts.append(f"rebound intraday {_fmt_pct(item['recovery_from_low'])}")
    if item["volume_ratio"] is not None:
        facts.append(f"vol x{item['volume_ratio']:.1f}")
    return (
        f"- {item['symbol']} ({item['exchange']}) {item['name']} | "
        f"{strategy_text} | " + ", ".join(facts)
    )


def _render_risk(item: dict) -> str:
    facts = [
        f"1d {_fmt_pct(item['change_1d'])}",
        f"close near low {item['close_position']:.0%}" if item["close_position"] is not None else None,
        f"dd20 {_fmt_pct(item['drawdown_20'])}",
    ]
    cleaned = [fact for fact in facts if fact]
    return f"- {item['symbol']} ({item['exchange']}) {item['name']} | falling knife risk | " + ", ".join(cleaned)


def _build_summary(
    *,
    group_name: str,
    config: dict,
    entries: list[WatchlistEntry],
    refresh_summary: dict,
    analyses: list[dict],
    history_days: int,
    max_movers: int,
    max_candidates: int,
    min_drop_pct: float,
    min_drawdown_pct: float,
) -> str:
    monthly_budget = int(config.get("monthly_symbol_budget", DEFAULT_MONTHLY_BUDGET))
    month_usage = _symbol_month_usage()
    latest_dates = sorted({item["date"] for item in analyses})
    movers_down = sorted(
        [item for item in analyses if item["change_1d"] is not None],
        key=lambda item: item["change_1d"],
    )[:max_movers]
    movers_up = sorted(
        [item for item in analyses if item["change_1d"] is not None],
        key=lambda item: item["change_1d"],
        reverse=True,
    )[:max_movers]
    rebound_candidates = sorted(
        [
            item
            for item in analyses
            if item["change_1d"] is not None
            and item["change_1d"] <= -abs(min_drop_pct)
            and item["drawdown_20"] is not None
            and item["drawdown_20"] <= -abs(min_drawdown_pct)
            and item["rebound_score"] >= 3
            and item["falling_knife_score"] <= 2
        ],
        key=lambda item: (-item["rebound_score"], item["change_1d"]),
    )[:max_candidates]
    falling_knives = sorted(
        [
            item
            for item in analyses
            if item["falling_knife_score"] >= 3
            and item["change_1d"] is not None
            and item["change_1d"] <= -abs(min_drop_pct)
        ],
        key=lambda item: item["change_1d"],
    )[:max_candidates]

    lines = [
        f"Market watch group: {group_name}",
        f"- Symbols analysed: {len(entries)}",
        f"- History window: {history_days} calendar days cached locally in SQLite",
        f"- Latest sessions in cache: {', '.join(latest_dates[-3:]) if latest_dates else 'none'}",
        f"- Marketstack budget tracker: {month_usage}/{monthly_budget} symbol-requests this month",
        (
            "- Last refresh: "
            f"{len(refresh_summary['refreshed_symbols'])} symbol(s) from Marketstack, "
            f"{len(refresh_summary['cache_only_symbols'])} served from cache"
        ),
        "- Note: the free Marketstack plan is too small for a full CAC-style daily scan; keep the daily group tight and expand on demand.",
        "",
        "Top drops:",
    ]
    if movers_down:
        lines.extend(_render_line(item) for item in movers_down)
    else:
        lines.append("- No cached movers yet.")

    lines.append("")
    lines.append("Top gains:")
    if movers_up:
        lines.extend(_render_line(item) for item in movers_up)
    else:
        lines.append("- No cached movers yet.")

    lines.append("")
    lines.append("Rebound candidates:")
    if rebound_candidates:
        lines.extend(_render_candidate(item) for item in rebound_candidates)
    else:
        lines.append("- No strong rebound setup detected with the current thresholds.")

    lines.append("")
    lines.append("Risky falling knives:")
    if falling_knives:
        lines.extend(_render_risk(item) for item in falling_knives)
    else:
        lines.append("- No obvious falling-knife setup in the current sample.")

    lines.append("")
    lines.append("Other strategy labels available:")
    lines.append("- capitulation rebound: big drop, intraday recovery, often after panic or event risk.")
    lines.append("- oversold mean reversion: multi-session washout, large drawdown versus recent highs.")
    lines.append("- trend pullback: dip within a broader uptrend, less violent than a panic selloff.")
    lines.append("- relative strength breakout: not a rebound, but useful to contrast with genuine weakness.")
    lines.append("")
    lines.append("Next step:")
    lines.append("- For 1 to 3 names only, use web_search/web_fetch to validate the why before acting.")
    return "\n".join(lines)


@register(
    name="market_watch",
    description=(
        "Refresh end-of-day market data from Marketstack with local SQLite caching, "
        "then analyze movers and rebound candidates for the configured watchlist."
    ),
    parameters={
        "type": "object",
        "properties": {
            "group": {
                "type": "string",
                "description": "Watchlist group name from skills/market-watch/watchlist.json. Defaults to the file's default_group.",
            },
            "refresh": {
                "type": "boolean",
                "description": "Fetch missing or stale EOD data from Marketstack before analyzing. Defaults to true.",
            },
            "force_refresh": {
                "type": "boolean",
                "description": "Force a historical backfill for the target group, even if cache exists. Defaults to false.",
            },
            "history_days": {
                "type": "integer",
                "description": "History window to analyze, capped by available cache and Marketstack plan limits. Defaults to 120.",
            },
            "max_movers": {
                "type": "integer",
                "description": "Maximum number of top rises and top falls to include. Defaults to 6.",
            },
            "max_candidates": {
                "type": "integer",
                "description": "Maximum number of rebound candidates and risky falling knives. Defaults to 5.",
            },
            "min_drop_pct": {
                "type": "number",
                "description": "Minimum 1-day drop percentage to flag a rebound candidate. Defaults to 4.0.",
            },
            "min_drawdown_pct": {
                "type": "number",
                "description": "Minimum drawdown versus the 20-day high to flag a rebound candidate. Defaults to 10.0.",
            },
        },
        "required": [],
    },
)
def market_watch(
    group: str | None = None,
    refresh: bool = True,
    force_refresh: bool = False,
    history_days: int = DEFAULT_HISTORY_DAYS,
    max_movers: int = DEFAULT_MAX_MOVERS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    min_drop_pct: float = DEFAULT_MIN_DROP_PCT,
    min_drawdown_pct: float = DEFAULT_MIN_DRAWNDOWN_PCT,
) -> str:
    try:
        group_name, entries, config = _resolve_watchlist(group)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return f"Error: {exc}"
    if not entries:
        return "Error: the resolved watchlist is empty."

    if refresh and not cfg.marketstack_api_key:
        return (
            "Error: MARKETSTACK_API_KEY is not configured. "
            f"Add it in the add-on options, then retry. Watchlist file: {_watchlist_abspath()}"
        )

    refresh_summary = {"refreshed_symbols": [], "cache_only_symbols": []}
    if refresh:
        try:
            refresh_summary = _refresh_market_data(entries, history_days, force_refresh)
        except Exception as exc:
            return f"Error: failed to refresh market data from Marketstack: {exc}"

    series = _load_series(entries, history_days)
    analyses: list[dict] = []
    missing_entries: list[str] = []
    for entry in entries:
        bars = series.get((entry.symbol, entry.exchange), [])
        analysis = _analyze_entry(entry, bars)
        if analysis is None:
            missing_entries.append(f"{entry.symbol}:{entry.exchange}")
            continue
        analyses.append(analysis)

    if not analyses:
        details = ", ".join(missing_entries) if missing_entries else "none"
        return (
            "Error: no usable market history is cached for this watchlist. "
            f"Entries without data: {details}. "
            "Run market_watch with refresh=true after configuring MARKETSTACK_API_KEY."
        )

    summary = _build_summary(
        group_name=group_name,
        config=config,
        entries=entries,
        refresh_summary=refresh_summary,
        analyses=analyses,
        history_days=history_days,
        max_movers=max_movers,
        max_candidates=max_candidates,
        min_drop_pct=min_drop_pct,
        min_drawdown_pct=min_drawdown_pct,
    )
    if missing_entries:
        summary += "\n\nMissing cache rows:\n- " + "\n- ".join(missing_entries[:10])
    return summary

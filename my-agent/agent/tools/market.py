"""Tool: market_watch — screen a watchlist by strategy (rebound / swing).

Runs entirely on Degiro data via the provider in `agent.degiro`. Strategies
are evaluated close-only (Degiro does not expose OHLV).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from agent import degiro, indicators
from agent.config import cfg
from agent.tools import register

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path("skills") / "market-watch" / "watchlist.json"
DEFAULT_GROUP = "core_daily"
DEFAULT_MAX_CANDIDATES = 8


@dataclass(frozen=True)
class WatchlistEntry:
    query: str
    label: str
    exchange_id: str | None
    currency: str | None


def _watchlist_abspath() -> Path:
    return Path(cfg.workspace_path) / WATCHLIST_PATH


def _load_watchlist() -> dict:
    path = _watchlist_abspath()
    if not path.exists():
        raise FileNotFoundError(
            f"Watchlist file not found: {path}. Populate it from the workspace template."
        )
    return json.loads(path.read_text())


def _available_groups() -> list[str]:
    """Best-effort list of valid `group` values for the tool schema.

    Read at import time, so changes to watchlist.json require a restart. If the
    file is unreachable we return an empty list and skip the enum constraint.
    """
    try:
        config = _load_watchlist()
    except Exception:
        return []
    groups = list(config.get("groups", {}).keys())
    return sorted({*groups, "all"})


def _default_group_name() -> str:
    try:
        config = _load_watchlist()
    except Exception:
        return DEFAULT_GROUP
    return config.get("default_group") or DEFAULT_GROUP


def _build_group_schema() -> dict:
    schema: dict = {
        "type": "string",
        "description": (
            f"Watchlist group name. Omit to use the default group "
            f"('{_default_group_name()}'); pass 'all' to scan every group."
        ),
    }
    enum = _available_groups()
    if enum:
        schema["enum"] = enum
    return schema


def _resolve_group(group: str | None) -> tuple[str, list[WatchlistEntry]]:
    config = _load_watchlist()
    groups = config.get("groups", {})
    default_name = config.get("default_group") or DEFAULT_GROUP
    target = group or default_name
    if target == "all":
        raw: list[dict] = []
        seen: set[str] = set()
        for name in groups:
            for item in groups[name]:
                key = (item.get("isin") or item.get("query") or "").upper()
                if key in seen:
                    continue
                seen.add(key)
                raw.append(item)
    else:
        raw = groups.get(target, [])
        if not raw:
            available = ", ".join(sorted(groups.keys())) or "(none)"
            raise ValueError(
                f"Unknown or empty watchlist group '{target}'. "
                f"Available: {available}, or 'all' to scan everything. "
                f"Omit the parameter to use the default group ('{default_name}')."
            )

    entries = []
    for item in raw:
        query = item.get("isin") or item.get("query") or item.get("symbol")
        if not query:
            continue
        entries.append(
            WatchlistEntry(
                query=str(query),
                label=str(item.get("label") or item.get("name") or query),
                exchange_id=item.get("exchange_id"),
                currency=item.get("currency"),
            )
        )
    return target, entries


def _analyze_entry(entry: WatchlistEntry, strategy: str) -> dict:
    try:
        ref = degiro.resolve_product(
            entry.query,
            exchange_id=entry.exchange_id,
            currency=entry.currency,
        )
    except Exception as exc:
        return {"entry": entry, "error": f"resolve failed: {exc}"}

    if not ref.vwd_id or not ref.history_ok:
        return {"entry": entry, "ref": ref, "error": "no usable price history"}

    try:
        rows = degiro.load_candles(
            ref.vwd_id, "1y-1d", vwd_identifier_type=ref.vwd_identifier_type
        )
    except Exception as exc:
        return {"entry": entry, "ref": ref, "error": f"candles fetch failed: {exc}"}

    closes = [r.close for r in rows]

    high_52w: float | None = None
    if ref.metadata_ok:
        try:
            meta = degiro.get_client().price_metadata(
                ref.vwd_id, ref.vwd_identifier_type
            )
            high_52w = meta.get("highPriceP1Y")
        except Exception as exc:
            logger.debug("metadata fetch failed for %s: %s", ref.symbol, exc)

    verdict = indicators.evaluate(strategy, closes, high_52w=high_52w)
    return {"entry": entry, "ref": ref, "verdict": verdict}


def _render_verdict(item: dict) -> str:
    entry: WatchlistEntry = item["entry"]
    ref = item.get("ref")
    label = entry.label
    if ref and ref.symbol:
        label = f"{ref.symbol} ({entry.label})"
    if "error" in item:
        return f"- {label}: skipped — {item['error']}"
    verdict = item["verdict"]
    reasons = "; ".join(verdict.reasons) if verdict.reasons else "no signal"
    return (
        f"- {label} | {verdict.signal} (score {verdict.score}) | {reasons}"
    )


@register(
    name="market_watch",
    description=(
        "Screen a watchlist for rebound or swing setups using Degiro close-only "
        "daily data. Returns ranked candidates, rejects ('falling knives' for "
        "rebound, trend breakdowns for swing) and neutrals. Use degiro_indicators "
        "or degiro_candles to zoom into a single name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "enum": ["rebound", "swing"],
                "description": "Screening strategy.",
            },
            "group": _build_group_schema(),
            "max_candidates": {
                "type": "integer",
                "description": f"Max candidates to list. Default {DEFAULT_MAX_CANDIDATES}.",
            },
        },
        "required": ["strategy"],
    },
)
def market_watch(
    strategy: str,
    group: str | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> str:
    if not degiro.degiro_available():
        return "Error: Degiro is not configured. Set degiro_username / degiro_password."
    if strategy not in ("rebound", "swing"):
        return "Error: strategy must be 'rebound' or 'swing'."

    try:
        group_name, entries = _resolve_group(group)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return f"Error: {exc}"
    if not entries:
        return "Error: the resolved watchlist is empty."

    results = [_analyze_entry(e, strategy) for e in entries]

    candidates = sorted(
        [r for r in results if "verdict" in r and r["verdict"].signal == "candidate"],
        key=lambda r: r["verdict"].score,
        reverse=True,
    )[:max_candidates]
    rejects = [
        r for r in results if "verdict" in r and r["verdict"].signal == "reject"
    ]
    neutrals = [
        r for r in results if "verdict" in r and r["verdict"].signal == "neutral"
    ]
    errors = [r for r in results if "error" in r]

    lines = [
        f"Market watch — strategy={strategy} | group={group_name} | entries={len(entries)}",
        "",
        f"Candidates ({len(candidates)}):",
    ]
    if candidates:
        lines.extend(_render_verdict(r) for r in candidates)
    else:
        lines.append("- none")

    label = "Falling knives" if strategy == "rebound" else "Trend breakdowns"
    lines.append("")
    lines.append(f"{label} ({len(rejects)}):")
    if rejects:
        lines.extend(_render_verdict(r) for r in rejects)
    else:
        lines.append("- none")

    lines.append("")
    lines.append(f"Neutral ({len(neutrals)}):")
    if neutrals:
        lines.extend(_render_verdict(r) for r in neutrals[:max_candidates])
    else:
        lines.append("- none")

    if errors:
        lines.append("")
        lines.append(f"Skipped ({len(errors)}):")
        lines.extend(_render_verdict(r) for r in errors)

    lines.append("")
    lines.append(
        "Note: Degiro is close-only — no volume / OHL confirmations. "
        "Cross-check with web_search / web_fetch on a named candidate before acting."
    )
    return "\n".join(lines)

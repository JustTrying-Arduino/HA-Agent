"""Portfolio and cash balances."""

from __future__ import annotations

from typing import Any

from . import endpoints as ep, products
from .http import DegiroHTTP
from .models import Position
from .session import SessionManager


def _unflatten(value_block: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in value_block:
        if "name" in item and "value" in item:
            out[item["name"]] = item["value"]
    return out


def _update_url(session: SessionManager) -> str:
    state = session.require()
    return f"{state.trading_url}{ep.UPDATE_PATH}{state.int_account};jsessionid={state.session_id}"


def get_portfolio(
    http: DegiroHTTP,
    session: SessionManager,
    *,
    only_open: bool = True,
) -> list[Position]:
    url = _update_url(session)
    resp = http.request("GET", url, params={"portfolio": 0})
    rows = resp.json().get("portfolio", {}).get("value", [])

    positions: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        flat = _unflatten(row.get("value", []))
        pid = str(row.get("id"))
        size = float(flat.get("size", 0) or 0)
        if only_open and size == 0:
            continue
        positions.append((pid, {**flat, "size": size}))

    if not positions:
        return []

    products_map = products.get_by_ids(http, session, [pid for pid, _ in positions])

    result: list[Position] = []
    for pid, flat in positions:
        prod = products_map.get(pid)
        result.append(
            Position(
                product_id=pid,
                symbol=prod.symbol if prod else None,
                name=prod.name if prod else None,
                isin=prod.isin if prod else None,
                currency=prod.currency if prod else None,
                vwd_id=prod.vwd_id if prod else None,
                size=float(flat.get("size", 0) or 0),
                avg_price=float(flat.get("breakEvenPrice", 0) or 0),
                current_price=float(flat.get("price", 0) or 0),
                market_value=float(flat.get("value", 0) or 0),
                pl_base=_pl_base(flat.get("plBase")),
                today_pl_base=_pl_base(flat.get("todayPlBase")),
            )
        )
    return result


def _pl_base(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        for v in raw.values():
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def get_cash(http: DegiroHTTP, session: SessionManager) -> dict[str, float]:
    url = _update_url(session)
    resp = http.request("GET", url, params={"cashFunds": 0})
    rows = resp.json().get("cashFunds", {}).get("value", [])
    out: dict[str, float] = {}
    for row in rows:
        flat = _unflatten(row.get("value", []))
        currency = flat.get("currencyCode")
        value = flat.get("value")
        if currency and value is not None:
            try:
                out[currency] = float(value)
            except (TypeError, ValueError):
                continue
    return out

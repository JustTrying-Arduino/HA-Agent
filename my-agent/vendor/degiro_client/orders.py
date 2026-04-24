"""Orders — read-only vendoring.

Upstream place_order / check_order / confirm_order / cancel_order are
intentionally NOT included here. Only get_orders (historical and current
open orders) is exposed.
"""

from __future__ import annotations

from typing import Any

from . import endpoints as ep, portfolio
from .http import DegiroHTTP
from .models import Order
from .session import SessionManager


def _update_url(session: SessionManager) -> str:
    state = session.require()
    return f"{state.trading_url}{ep.UPDATE_PATH}{state.int_account};jsessionid={state.session_id}"


def get_orders(
    http: DegiroHTTP,
    session: SessionManager,
    *,
    historical: bool = False,
) -> list[Order]:
    url = _update_url(session)
    key = "historicalOrders" if historical else "orders"
    resp = http.request("GET", url, params={key: 0})
    rows = resp.json().get(key, {}).get("value", [])
    result: list[Order] = []
    for row in rows:
        flat = portfolio._unflatten(row.get("value", []))
        result.append(
            Order(
                order_id=str(row.get("id") or flat.get("id", "")),
                product_id=str(flat.get("productId", "")),
                buy_sell=str(flat.get("buysell") or flat.get("buySell", "")),
                order_type=int(flat.get("orderTypeId", -1)),
                size=float(flat.get("size", 0) or 0),
                price=_opt_float(flat.get("price")),
                stop_price=_opt_float(flat.get("stopPrice")),
                time_type=int(flat.get("orderTimeTypeId", -1)),
                raw=flat,
            )
        )
    return result


def _opt_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None

"""Order lifecycle: check -> confirm -> execute. Plus list/cancel.

Degiro requires two steps: POST /v5/checkOrder gives back a confirmationId
and a preview (fees, estimated total). Then POST /v5/order/{confirmationId}
with the same body executes it.
"""

from __future__ import annotations

from typing import Any

from . import endpoints as ep, portfolio
from .http import DegiroHTTP
from .models import Order
from .session import SessionManager


def _resolve_order_type(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return ep.ORDER_TYPES[value.upper()]


def _resolve_time_type(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return ep.TIME_TYPES[value.upper()]


def _resolve_action(value: str) -> str:
    action = value.upper()
    if action not in ep.ORDER_ACTIONS:
        raise ValueError(f"buy_sell must be BUY or SELL, got {value!r}")
    return action


def check_order(
    http: DegiroHTTP,
    session: SessionManager,
    *,
    product_id: str,
    buy_sell: str,
    size: float,
    order_type: str | int,
    time_type: str | int = "DAY",
    price: float | None = None,
    stop_price: float | None = None,
) -> dict[str, Any]:
    state = session.require()
    body: dict[str, Any] = {
        "buySell": _resolve_action(buy_sell),
        "orderType": _resolve_order_type(order_type),
        "productId": str(product_id),
        "size": size,
        "timeType": _resolve_time_type(time_type),
    }
    if price is not None:
        body["price"] = price
    if stop_price is not None:
        body["stopPrice"] = stop_price

    url = f"{state.trading_url}{ep.CHECK_ORDER_PATH};jsessionid={state.session_id}"
    params = {"intAccount": state.int_account, "sessionId": state.session_id}
    resp = http.request("POST", url, params=params, json=body)
    payload = resp.json()
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"checkOrder rejected: {errors}")
    data = payload.get("data", {})
    return {"confirmation_id": data.get("confirmationId"), "preview": data, "body": body}


def confirm_order(
    http: DegiroHTTP,
    session: SessionManager,
    *,
    confirmation_id: str,
    body: dict[str, Any],
) -> str:
    state = session.require()
    url = f"{state.trading_url}{ep.ORDER_PATH}{confirmation_id};jsessionid={state.session_id}"
    params = {"intAccount": state.int_account, "sessionId": state.session_id}
    resp = http.request("POST", url, params=params, json=body)
    data = resp.json().get("data", {})
    order_id = data.get("orderId")
    if not order_id:
        raise RuntimeError(f"confirm_order did not return orderId: {data}")
    return order_id


def place_order(
    http: DegiroHTTP,
    session: SessionManager,
    *,
    product_id: str,
    buy_sell: str,
    size: float,
    order_type: str | int,
    time_type: str | int = "DAY",
    price: float | None = None,
    stop_price: float | None = None,
) -> str:
    check = check_order(
        http,
        session,
        product_id=product_id,
        buy_sell=buy_sell,
        size=size,
        order_type=order_type,
        time_type=time_type,
        price=price,
        stop_price=stop_price,
    )
    return confirm_order(
        http,
        session,
        confirmation_id=check["confirmation_id"],
        body=check["body"],
    )


def cancel_order(http: DegiroHTTP, session: SessionManager, order_id: str) -> None:
    state = session.require()
    url = f"{state.trading_url}{ep.ORDER_PATH}{order_id};jsessionid={state.session_id}"
    params = {"intAccount": state.int_account, "sessionId": state.session_id}
    http.request("DELETE", url, params=params)


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

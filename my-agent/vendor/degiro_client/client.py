"""Public facade: one DegiroClient instance exposes Degiro account operations.

Order-placement methods (place_order, check_order, confirm_order,
cancel_order) are exposed here. The HA-Agent safety net for human-in-the-loop
trading lives at the application layer (pending_actions table + Telegram
inline-keyboard callback + per-action guards), not at the vendor level. See
VENDORED.md for details.

Typical usage:

    from degiro_client import DegiroClient
    c = DegiroClient()
    positions = c.get_portfolio()
    quote = c.price_now(vwd_id)
"""

from __future__ import annotations

from typing import Any

from . import account, orders, portfolio, prices, products, storage
from .http import DegiroHTTP
from .models import Candle, Credentials, Order, Position, Product, Quote, SessionState
from .session import SessionManager


class DegiroClient:
    def __init__(self) -> None:
        self._session = SessionManager()
        self._http = DegiroHTTP(self._session)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "DegiroClient":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()

    def login(
        self,
        username: str,
        password: str,
        totp_seed: str | None = None,
        *,
        persist: bool = True,
    ) -> SessionState:
        creds = Credentials(username=username, password=password, totp_seed=totp_seed)
        state = self._session.force_login(creds)
        if persist:
            storage.save_credentials(creds)
        return state

    def logout(self) -> None:
        storage.delete_credentials()
        storage.delete_session()
        self._session.invalidate()

    @property
    def session(self) -> SessionState | None:
        return self._session.state

    def account_info(self) -> dict[str, Any]:
        return account.get_account_info(self._http, self._session)

    def get_portfolio(self, *, only_open: bool = True) -> list[Position]:
        return portfolio.get_portfolio(self._http, self._session, only_open=only_open)

    def get_cash(self) -> dict[str, float]:
        return portfolio.get_cash(self._http, self._session)

    def search_products(
        self, query: str, *, limit: int = 10, product_type: int | None = None
    ) -> list[Product]:
        return products.search(
            self._http, self._session, query, limit=limit, product_type=product_type
        )

    def get_products_by_ids(self, ids: list[str]) -> dict[str, Product]:
        return products.get_by_ids(self._http, self._session, ids)

    def get_orders(self, *, historical: bool = False) -> list[Order]:
        return orders.get_orders(self._http, self._session, historical=historical)

    def check_order(
        self,
        *,
        product_id: str,
        buy_sell: str,
        size: float,
        order_type: str | int,
        time_type: str | int = "DAY",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        return orders.check_order(
            self._http,
            self._session,
            product_id=product_id,
            buy_sell=buy_sell,
            size=size,
            order_type=order_type,
            time_type=time_type,
            price=price,
            stop_price=stop_price,
        )

    def confirm_order(self, *, confirmation_id: str, body: dict[str, Any]) -> str:
        return orders.confirm_order(
            self._http, self._session, confirmation_id=confirmation_id, body=body
        )

    def place_order(
        self,
        *,
        product_id: str,
        buy_sell: str,
        size: float,
        order_type: str | int,
        time_type: str | int = "DAY",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        return orders.place_order(
            self._http,
            self._session,
            product_id=product_id,
            buy_sell=buy_sell,
            size=size,
            order_type=order_type,
            time_type=time_type,
            price=price,
            stop_price=stop_price,
        )

    def cancel_order(self, order_id: str) -> None:
        orders.cancel_order(self._http, self._session, order_id)

    def price_now(
        self, vwd_id: str, vwd_identifier_type: str | None = None
    ) -> Quote:
        return prices.price_now(
            self._http,
            self._session,
            vwd_id,
            vwd_identifier_type=vwd_identifier_type or "issueid",
        )

    def price_metadata(
        self, vwd_id: str, vwd_identifier_type: str | None = None
    ) -> dict[str, Any]:
        """Rich product metadata from the vwd charting backend.

        Fields observed (not exhaustive, vwd may return more):
          previousClosePrice, lastPrice, currency, lastTime,
          highPrice, lowPrice, highPriceP1Y, lowPriceP1Y,
          cumulativeVolume, windowHighPrice, windowLowPrice,
          windowOpenPrice, windowPreviousClosePrice.

        EU products use vwd_identifier_type="issueid"; US products use "vwdkey".
        """
        return prices.metadata(
            self._http,
            self._session,
            vwd_id,
            vwd_identifier_type=vwd_identifier_type or "issueid",
        )

    def price_history(
        self,
        vwd_id: str,
        *,
        period: str = "P1Y",
        resolution: str = "P1D",
        vwd_identifier_type: str | None = None,
    ) -> list[Candle]:
        return prices.price_history(
            self._http,
            self._session,
            vwd_id,
            period=period,
            resolution=resolution,
            vwd_identifier_type=vwd_identifier_type or "issueid",
        )

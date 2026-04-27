"""Plain dataclasses for Degiro entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Credentials:
    username: str
    password: str
    totp_seed: str | None = None


@dataclass
class SessionState:
    session_id: str
    int_account: int
    client_id: int
    trading_url: str
    pa_url: str
    product_search_url: str
    dictionary_url: str
    reporting_url: str
    user_token: int | None = None
    last_activity: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "int_account": self.int_account,
            "client_id": self.client_id,
            "trading_url": self.trading_url,
            "pa_url": self.pa_url,
            "product_search_url": self.product_search_url,
            "dictionary_url": self.dictionary_url,
            "reporting_url": self.reporting_url,
            "user_token": self.user_token,
            "last_activity": self.last_activity.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        return cls(
            session_id=data["session_id"],
            int_account=data["int_account"],
            client_id=data["client_id"],
            trading_url=data["trading_url"],
            pa_url=data["pa_url"],
            product_search_url=data["product_search_url"],
            dictionary_url=data["dictionary_url"],
            reporting_url=data["reporting_url"],
            user_token=data.get("user_token"),
            last_activity=datetime.fromisoformat(data["last_activity"]),
        )


@dataclass
class Position:
    product_id: str
    symbol: str | None
    name: str | None
    isin: str | None
    currency: str | None
    vwd_id: str | None
    size: float
    avg_price: float
    current_price: float
    market_value: float
    pl_base: float | None = None
    today_pl_base: float | None = None


@dataclass
class Product:
    id: str
    symbol: str | None
    name: str | None
    isin: str | None
    currency: str | None
    vwd_id: str | None
    product_type: str | None
    exchange_id: str | None
    vwd_identifier_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    order_id: str
    product_id: str
    buy_sell: str
    order_type: int
    size: float
    price: float | None
    stop_price: float | None
    time_type: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Quote:
    price: float
    timestamp: datetime
    currency: str | None = None


@dataclass
class Candle:
    """Historical candle. Degiro currently only populates `close` and `timestamp`."""

    timestamp: datetime
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None

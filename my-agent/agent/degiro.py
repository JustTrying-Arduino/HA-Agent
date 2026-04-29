"""Degiro provider: singleton client, credential fingerprint, product resolver,
candles cache with UTC conversion.

The vendored `degiro_client` package (my-agent/vendor/) exposes no order-
placement methods, by construction. See vendor/degiro_client/VENDORED.md.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from agent.config import cfg
from agent.db import commit, fetchall, fetchone, get_db
from degiro_client import Candle, DegiroClient, Product

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")

# Heuristic: when the official close-of-day for the primary market of a
# given currency is published and stable. Used to decide whether the
# cached "today" daily bar is trustworthy or still intra-session.
EU_CLOSE_SETTLE_HOUR = 18
EU_CLOSE_SETTLE_MINUTE = 5
US_CLOSE_SETTLE_HOUR = 22
US_CLOSE_SETTLE_MINUTE = 30

PRODUCT_CACHE_TTL = timedelta(days=7)

WINDOW_MAP: dict[str, tuple[str, str]] = {
    "today-10m": ("P1D", "PT10M"),
    "5d-1h": ("P5D", "PT1H"),
    "1m-1d": ("P1M", "P1D"),
    "3m-1d": ("P3M", "P1D"),
    "1y-1d": ("P1Y", "P1D"),
    "5y-1w": ("P5Y", "P7D"),
}

CANDLE_TTL: dict[str, timedelta] = {
    "PT10M": timedelta(minutes=5),
    "PT15M": timedelta(minutes=5),
    "PT1H": timedelta(minutes=30),
    "P1D": timedelta(hours=8),
    "P7D": timedelta(days=1),
}

_client: DegiroClient | None = None
_client_lock = threading.Lock()


def degiro_available() -> bool:
    return bool(cfg.degiro_username and cfg.degiro_password)


def _data_dir() -> Path:
    explicit = os.environ.get("DEGIRO_DATA_DIR")
    if explicit:
        return Path(explicit)
    return Path("/data/degiro")


def _fingerprint_path() -> Path:
    return _data_dir() / ".creds_fingerprint"


def _compute_fingerprint(username: str, password: str, totp_seed: str) -> str:
    key = os.environ.get("DEGIRO_KEY", "").encode("utf-8")
    msg = f"{username}|{password}|{totp_seed or ''}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _load_fingerprint() -> str | None:
    path = _fingerprint_path()
    if not path.exists():
        return None
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def _store_fingerprint(fp: str) -> None:
    path = _fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fp)
    os.chmod(path, 0o600)


def get_client() -> DegiroClient:
    """Lazy singleton. Handles initial login and credential-change relogin."""
    global _client
    if not degiro_available():
        raise RuntimeError(
            "Degiro is not configured — set degiro_username / degiro_password "
            "in the add-on options."
        )
    with _client_lock:
        if _client is None:
            _client = DegiroClient()
        current_fp = _compute_fingerprint(
            cfg.degiro_username, cfg.degiro_password, cfg.degiro_totp_seed
        )
        stored_fp = _load_fingerprint()
        needs_login = stored_fp != current_fp or _client.session is None
        if needs_login:
            logger.info("Degiro: (re)logging in (fingerprint changed or no session)")
            _client.login(
                cfg.degiro_username,
                cfg.degiro_password,
                cfg.degiro_totp_seed or None,
                persist=True,
            )
            _store_fingerprint(current_fp)
    return _client


def place_limit_gtc(
    *, product_id: str, buy_sell: str, size: float, limit_price: float
) -> str:
    """Place a LIMIT, GTC ('PERMANENT') order. Returns the Degiro orderId."""
    client = get_client()
    return client.place_order(
        product_id=str(product_id),
        buy_sell=buy_sell,
        size=float(size),
        order_type="LIMITED",
        time_type="PERMANENT",
        price=float(limit_price),
    )


def cancel_order(order_id: str) -> None:
    get_client().cancel_order(str(order_id))


def list_open_orders() -> list:
    return get_client().get_orders(historical=False)


def is_today_bar_settled(currency: str | None, *, now: datetime | None = None) -> bool:
    """Return True if today's official close for `currency`'s primary market
    is published and stable. Heuristic by currency: USD → NYSE/NASDAQ
    (close 22:00 Paris, settle by 22:30); anything else → Euronext-like
    (close 17:30 Paris, settle by 18:05). The `now` argument is only used
    by tests."""
    paris_now = (now or datetime.now(PARIS_TZ)).astimezone(PARIS_TZ)
    if (currency or "EUR").upper() == "USD":
        h, m = US_CLOSE_SETTLE_HOUR, US_CLOSE_SETTLE_MINUTE
    else:
        h, m = EU_CLOSE_SETTLE_HOUR, EU_CLOSE_SETTLE_MINUTE
    return (paris_now.hour, paris_now.minute) >= (h, m)


def _paris_to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS_TZ)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Product resolution
# ---------------------------------------------------------------------------


@dataclass
class ProductRef:
    query_norm: str
    isin: str | None
    product_id: str | None
    vwd_id: str | None
    vwd_identifier_type: str | None
    symbol: str | None
    name: str | None
    currency: str | None
    exchange_id: str | None
    history_ok: bool
    metadata_ok: bool


def _normalize_query(
    query: str,
    *,
    exchange_id: str | None = None,
    currency: str | None = None,
) -> str:
    q = query.strip()
    if not q:
        return ""
    # Simple ISIN detection: 12 alphanumeric chars.
    if len(q) == 12 and q.isalnum() and any(c.isalpha() for c in q):
        base = f"isin:{q.upper()}"
    else:
        base = f"q:{q.lower()}"
    parts = [base]
    if exchange_id:
        parts.append(f"exch:{exchange_id}")
    if currency:
        parts.append(f"ccy:{currency.upper()}")
    return "|".join(parts)


def _row_to_ref(row) -> ProductRef:
    return ProductRef(
        query_norm=row["query_norm"],
        isin=row["isin"],
        product_id=row["product_id"],
        vwd_id=row["vwd_id"],
        vwd_identifier_type=row["vwd_identifier_type"],
        symbol=row["symbol"],
        name=row["name"],
        currency=row["currency"],
        exchange_id=row["exchange_id"],
        history_ok=bool(row["history_ok"]),
        metadata_ok=bool(row["metadata_ok"]),
    )


def _cache_get_product(query_norm: str) -> ProductRef | None:
    row = fetchone(
        "SELECT * FROM degiro_products WHERE query_norm = ?",
        (query_norm,),
    )
    if row is None:
        return None
    fetched_at = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
    if datetime.now(UTC) - fetched_at > PRODUCT_CACHE_TTL:
        return None
    return _row_to_ref(row)


def _cache_put_product(ref: ProductRef) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO degiro_products(
            query_norm, isin, product_id, vwd_id, vwd_identifier_type,
            symbol, name, currency, exchange_id, history_ok, metadata_ok,
            fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(query_norm) DO UPDATE SET
            isin = excluded.isin,
            product_id = excluded.product_id,
            vwd_id = excluded.vwd_id,
            vwd_identifier_type = excluded.vwd_identifier_type,
            symbol = excluded.symbol,
            name = excluded.name,
            currency = excluded.currency,
            exchange_id = excluded.exchange_id,
            history_ok = excluded.history_ok,
            metadata_ok = excluded.metadata_ok,
            fetched_at = excluded.fetched_at
        """,
        (
            ref.query_norm,
            ref.isin,
            ref.product_id,
            ref.vwd_id,
            ref.vwd_identifier_type,
            ref.symbol,
            ref.name,
            ref.currency,
            ref.exchange_id,
            int(ref.history_ok),
            int(ref.metadata_ok),
            _now_utc_iso(),
        ),
    )
    commit()


def _pick_best(
    candidates: list[Product],
    *,
    isin: str | None,
    exchange_id: str | None,
    currency: str | None,
) -> Product | None:
    filtered = candidates
    if isin:
        exact = [p for p in filtered if p.isin and p.isin.upper() == isin.upper()]
        if exact:
            filtered = exact
    if exchange_id:
        narrowed = [p for p in filtered if p.exchange_id == exchange_id]
        if narrowed:
            filtered = narrowed
    if currency:
        narrowed = [p for p in filtered if p.currency == currency]
        if narrowed:
            filtered = narrowed
    if not filtered:
        return None
    with_vwd = [p for p in filtered if p.vwd_id]
    return (with_vwd or filtered)[0]


def _validate_history(
    client: DegiroClient, vwd_id: str, vwd_identifier_type: str | None
) -> bool:
    try:
        candles = client.price_history(
            vwd_id,
            period="P1M",
            resolution="P1D",
            vwd_identifier_type=vwd_identifier_type,
        )
        return len(candles) >= 5
    except Exception as exc:
        logger.warning("price_history validation failed for %s: %s", vwd_id, exc)
        return False


def _validate_metadata(
    client: DegiroClient, vwd_id: str, vwd_identifier_type: str | None
) -> bool:
    try:
        meta = client.price_metadata(vwd_id, vwd_identifier_type)
        return bool(meta)
    except Exception as exc:
        logger.warning("price_metadata validation failed for %s: %s", vwd_id, exc)
        return False


def resolve_product(
    query: str,
    *,
    exchange_id: str | None = None,
    currency: str | None = None,
    refresh: bool = False,
) -> ProductRef:
    """Resolve a symbol / ISIN / name to a stable ProductRef.

    Uses the `degiro_products` cache (TTL 7d) and validates via a short
    price_history probe + metadata probe.
    """
    query_norm = _normalize_query(query, exchange_id=exchange_id, currency=currency)
    if not query_norm:
        raise ValueError("Empty query")
    if not refresh:
        cached = _cache_get_product(query_norm)
        if cached is not None:
            return cached

    client = get_client()
    candidates = client.search_products(query, limit=20)
    if not candidates:
        raise RuntimeError(f"No Degiro product found for query: {query!r}")

    isin_hint = query.strip() if query_norm.startswith("isin:") else None
    best = _pick_best(
        candidates,
        isin=isin_hint,
        exchange_id=exchange_id,
        currency=currency,
    )
    if best is None:
        raise RuntimeError(
            f"Degiro returned {len(candidates)} candidates for {query!r} "
            "but none matched the provided filters."
        )

    vwd_id = best.vwd_id
    vwd_identifier_type = best.vwd_identifier_type
    history_ok = bool(vwd_id) and _validate_history(
        client, vwd_id, vwd_identifier_type
    )
    metadata_ok = bool(vwd_id) and _validate_metadata(
        client, vwd_id, vwd_identifier_type
    )

    ref = ProductRef(
        query_norm=query_norm,
        isin=best.isin,
        product_id=best.id,
        vwd_id=vwd_id,
        vwd_identifier_type=vwd_identifier_type,
        symbol=best.symbol,
        name=best.name,
        currency=best.currency,
        exchange_id=best.exchange_id,
        history_ok=history_ok,
        metadata_ok=metadata_ok,
    )
    _cache_put_product(ref)
    return ref


# ---------------------------------------------------------------------------
# Candles cache
# ---------------------------------------------------------------------------


@dataclass
class CandleRow:
    ts: str  # UTC ISO 8601 with trailing Z
    close: float


def window_to_period_resolution(window: str) -> tuple[str, str]:
    if window not in WINDOW_MAP:
        allowed = ", ".join(WINDOW_MAP.keys())
        raise ValueError(f"Unknown window '{window}'. Allowed: {allowed}")
    return WINDOW_MAP[window]


def _latest_fetched_at(vwd_id: str, resolution: str) -> datetime | None:
    row = fetchone(
        "SELECT MAX(fetched_at) AS t FROM degiro_prices WHERE vwd_id = ? AND resolution = ?",
        (vwd_id, resolution),
    )
    raw = row["t"] if row else None
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _latest_bar_ts(vwd_id: str, resolution: str) -> datetime | None:
    row = fetchone(
        "SELECT MAX(ts) AS t FROM degiro_prices WHERE vwd_id = ? AND resolution = ?",
        (vwd_id, resolution),
    )
    raw = row["t"] if row else None
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _candles_are_fresh(vwd_id: str, resolution: str) -> bool:
    latest = _latest_fetched_at(vwd_id, resolution)
    if latest is None:
        return False
    ttl = CANDLE_TTL.get(resolution, timedelta(hours=8))
    return datetime.now(UTC) - latest < ttl


def _persist_candles(vwd_id: str, resolution: str, candles: list[Candle]) -> None:
    if not candles:
        return
    db = get_db()
    fetched_at = _now_utc_iso()
    rows = [
        (
            vwd_id,
            resolution,
            _paris_to_utc_iso(c.timestamp),
            float(c.close),
            c.open,
            c.high,
            c.low,
            c.volume,
            fetched_at,
        )
        for c in candles
    ]
    db.executemany(
        """
        INSERT INTO degiro_prices(
            vwd_id, resolution, ts, close, open, high, low, volume, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(vwd_id, resolution, ts) DO UPDATE SET
            close = excluded.close,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            volume = excluded.volume,
            fetched_at = excluded.fetched_at
        """,
        rows,
    )
    commit()


def load_candles(
    vwd_id: str,
    window: str,
    *,
    refresh: bool = True,
    vwd_identifier_type: str | None = None,
    currency: str | None = None,
) -> list[CandleRow]:
    """Fetch candles (or return cached), persist to SQLite, return close-only rows.

    `currency` lets the cache decide whether today's daily bar is settled:
    if a daily bar dated today is in cache but the market hasn't settled yet
    (Euronext < 18:05, NYSE/NASDAQ < 22:30 Paris), force a refresh — the
    cached close is intra-session noise.
    """
    period, resolution = window_to_period_resolution(window)
    force_refresh = False
    if refresh and resolution == "P1D":
        latest_bar = _latest_bar_ts(vwd_id, resolution)
        if latest_bar is not None:
            today_paris = datetime.now(PARIS_TZ).date()
            if (
                latest_bar.astimezone(PARIS_TZ).date() == today_paris
                and not is_today_bar_settled(currency)
            ):
                force_refresh = True
    if refresh and (force_refresh or not _candles_are_fresh(vwd_id, resolution)):
        client = get_client()
        candles = client.price_history(
            vwd_id,
            period=period,
            resolution=resolution,
            vwd_identifier_type=vwd_identifier_type,
        )
        _persist_candles(vwd_id, resolution, candles)

    rows = fetchall(
        "SELECT ts, close FROM degiro_prices WHERE vwd_id = ? AND resolution = ? ORDER BY ts ASC",
        (vwd_id, resolution),
    )
    return [CandleRow(ts=r["ts"], close=float(r["close"])) for r in rows]

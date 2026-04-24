"""Current and historical prices via Degiro's charting backend (vwdservices).

Known limitations:
- price_history() returns close-only candles. open/high/low/volume are NOT
  populated by the vwd backend. Consumers should treat those fields as
  always-None.
- resolution="P1W" requested returns period="P7D" in practice. Our consumer
  (HA-Agent) treats P7D as the canonical weekly resolution.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from . import endpoints as ep
from .http import DegiroHTTP
from .models import Candle, Quote
from .session import SessionManager


class PricesNotConfigured(RuntimeError):
    """Raised when userToken is missing."""


def _user_token(session: SessionManager) -> int:
    state = session.require()
    if state.user_token is None:
        raise PricesNotConfigured(
            "userToken missing — log in first (auth.py attempts to populate it)."
        )
    return state.user_token


def _strip_jsonp(text: str) -> str:
    text = text.strip()
    if text.endswith(")"):
        open_paren = text.find("(")
        if open_paren > 0 and not text.startswith("{") and not text.startswith("["):
            return text[open_paren + 1 : -1]
    return text


def _fetch(
    http: DegiroHTTP,
    session: SessionManager,
    vwd_id: str,
    *,
    resolution: str,
    period: str,
) -> dict[str, Any]:
    token = _user_token(session)
    params: list[tuple[str, Any]] = [
        ("requestid", 1),
        ("resolution", resolution),
        ("culture", "fr-FR"),
        ("period", period),
        ("series", f"issueid:{vwd_id}"),
        ("series", f"price:issueid:{vwd_id}"),
        ("format", "json"),
        ("userToken", token),
        ("tz", "Europe/Paris"),
    ]
    resp = http._client.get(
        ep.VWD_CHART_URL,
        params=params,
        headers={
            "User-Agent": ep.USER_AGENT,
            "Referer": ep.REFERER,
            "Accept": "application/json, text/plain, */*",
        },
    )
    resp.raise_for_status()
    return json.loads(_strip_jsonp(resp.text))


def _find_series(payload: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    for s in payload.get("series", []):
        if s.get("id", "").startswith(prefix):
            return s
    return None


_TIMES_RE = re.compile(
    r"^(?P<start>\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2})?)/(?P<res>P.+)$"
)


def _parse_times(times: str | None) -> tuple[datetime, timedelta] | None:
    if not times:
        return None
    m = _TIMES_RE.match(times)
    if not m:
        return None
    start_str = m.group("start")
    if "T" not in start_str:
        start_str += "T00:00:00"
    start = datetime.fromisoformat(start_str)
    return start, _iso_duration_to_timedelta(m.group("res"))


_ISO_DUR_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<mins>\d+)M)?(?:(?P<secs>\d+)S)?)?$"
)


def _iso_duration_to_timedelta(dur: str) -> timedelta:
    m = _ISO_DUR_RE.match(dur)
    if not m:
        return {
            "P1W": timedelta(weeks=1),
            "P1M": timedelta(days=30),
            "P1Y": timedelta(days=365),
        }.get(dur, timedelta(days=1))
    parts = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    return timedelta(
        days=parts["days"],
        hours=parts["hours"],
        minutes=parts["mins"],
        seconds=parts["secs"],
    )


def price_now(http: DegiroHTTP, session: SessionManager, vwd_id: str) -> Quote:
    payload = _fetch(http, session, vwd_id, resolution="PT1M", period="P1D")
    meta = _find_series(payload, "issueid:")
    if not meta or "data" not in meta:
        raise RuntimeError(f"no metadata series for vwdId={vwd_id}: {payload}")
    d = meta["data"]
    last_price = d.get("lastPrice")
    last_time = d.get("lastTime")
    if last_price is None:
        raise RuntimeError(f"no lastPrice for vwdId={vwd_id}: {d}")
    ts = datetime.fromisoformat(last_time) if last_time else datetime.utcnow()
    return Quote(price=float(last_price), timestamp=ts, currency=d.get("currency"))


def price_history(
    http: DegiroHTTP,
    session: SessionManager,
    vwd_id: str,
    *,
    period: str = "P1Y",
    resolution: str = "P1D",
) -> list[Candle]:
    payload = _fetch(http, session, vwd_id, resolution=resolution, period=period)
    price_s = _find_series(payload, "price:")
    if not price_s:
        raise RuntimeError(f"no price series in response for vwdId={vwd_id}: {payload}")
    parsed = _parse_times(price_s.get("times"))
    if parsed is None:
        raise RuntimeError(
            f"cannot parse times={price_s.get('times')!r} for vwdId={vwd_id}"
        )
    start, step = parsed

    # Dedupe duplicate offsets (vwd sometimes repeats, keeping the later value).
    # Offsets can be fractional for intraday resolutions — keep them as floats
    # so PT10M/PT15M series are not truncated to integer slots.
    seen: dict[float, float] = {}
    for offset, value in price_s.get("data", []):
        seen[float(offset)] = float(value)

    return [
        Candle(timestamp=start + step * off, close=val)
        for off, val in sorted(seen.items())
    ]


def metadata(
    http: DegiroHTTP, session: SessionManager, vwd_id: str
) -> dict[str, Any]:
    """Rich metadata for a product (trading hours, bid/ask context, 52w range, …)."""
    payload = _fetch(http, session, vwd_id, resolution="PT1M", period="P1D")
    meta = _find_series(payload, "issueid:")
    return meta.get("data", {}) if meta else {}

"""Account info endpoints (kept minimal — most metadata lives in SessionState)."""

from __future__ import annotations

from typing import Any

from . import endpoints as ep
from .http import DegiroHTTP
from .session import SessionManager


def get_account_info(http: DegiroHTTP, session: SessionManager) -> dict[str, Any]:
    state = session.require()
    url = (
        f"{state.trading_url}{ep.ACCOUNT_INFO_PATH}"
        f"{state.int_account};jsessionid={state.session_id}"
    )
    resp = http.request("GET", url)
    return resp.json().get("data", {})

"""Degiro login flow.

POSTs to /login/secure/login/totp when a TOTP seed is provided,
else /login/secure/login. Extracts sessionId from the JSON response body
(not from a Set-Cookie header — confirmed from the reference TS repo).

Then fetches /login/secure/config and {paUrl}client to populate the rest
of the SessionState.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pyotp

from . import endpoints as ep
from .models import Credentials, SessionState


class LoginError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://trader.degiro.nl",
        "Referer": "https://trader.degiro.nl/login/fr",
        "User-Agent": ep.USER_AGENT,
    }


def _auth_headers(session_id: str) -> dict[str, str]:
    return {
        "Cookie": f"JSESSIONID={session_id};",
        "Referer": ep.REFERER,
        "Accept": "application/json, text/plain, */*",
        "User-Agent": ep.USER_AGENT,
    }


def login(creds: Credentials, client: httpx.Client | None = None) -> SessionState:
    """Full login flow. Returns a populated SessionState."""
    own_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        session_id = _do_login(creds, client)
        config = _fetch_config(session_id, client)
        client_info = _fetch_client_info(session_id, config["paUrl"], client)
        user_token = _resolve_user_token(
            client_info, session_id, config["tradingUrl"], client_info["intAccount"], client
        )
        return SessionState(
            session_id=session_id,
            int_account=client_info["intAccount"],
            client_id=client_info["id"],
            trading_url=config["tradingUrl"],
            pa_url=config["paUrl"],
            product_search_url=config["productSearchUrl"],
            dictionary_url=config["dictionaryUrl"],
            reporting_url=config["reportingUrl"],
            user_token=user_token,
            last_activity=datetime.utcnow(),
        )
    finally:
        if own_client:
            client.close()


def _resolve_user_token(
    client_info: dict,
    session_id: str,
    trading_url: str,
    int_account: int,
    client: httpx.Client,
) -> int | None:
    token = _fetch_user_token_from_account_info(
        session_id, trading_url, int_account, client
    )
    if token is not None:
        return token
    return client_info.get("id")


def _fetch_user_token_from_account_info(
    session_id: str,
    trading_url: str,
    int_account: int,
    client: httpx.Client,
) -> int | None:
    from . import endpoints as ep

    url = (
        f"{trading_url}{ep.ACCOUNT_INFO_PATH}{int_account};jsessionid={session_id}"
    )
    try:
        resp = client.get(url, headers=_auth_headers(session_id))
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", {})
        for key in ("userToken", "clientId"):
            if key in data and isinstance(data[key], int):
                return data[key]
    except (httpx.HTTPError, ValueError):
        return None
    return None


def _do_login(creds: Credentials, client: httpx.Client) -> str:
    body = {
        "isPassCodeReset": False,
        "isRedirectToMobile": False,
        "username": creds.username.strip().lower(),
        "password": creds.password,
        "queryParams": {"reason": "session_expired"},
    }
    if creds.totp_seed:
        try:
            body["oneTimePassword"] = pyotp.TOTP(creds.totp_seed).now()
        except Exception as exc:
            raise LoginError(
                "Invalid TOTP seed. Expected a base32 string."
            ) from exc
        url = ep.BASE_URL + ep.LOGIN_TOTP_PATH
    else:
        url = ep.BASE_URL + ep.LOGIN_PATH

    resp = client.post(url, json=body, headers=_headers())
    return _extract_session_id(resp, url)


def _extract_session_id(resp: httpx.Response, url: str) -> str:
    if resp.status_code >= 400:
        raise LoginError(
            f"Login failed: POST {url} → HTTP {resp.status_code} "
            f"ct={resp.headers.get('content-type')!r} body={resp.text[:300]!r}"
        )
    ct = resp.headers.get("content-type", "")
    if "json" not in ct.lower():
        raise LoginError(
            f"Login returned non-JSON response (HTTP {resp.status_code}, "
            f"content-type={ct!r}). First bytes: {resp.text[:300]!r}."
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise LoginError(
            f"Login returned invalid JSON (HTTP {resp.status_code}): {resp.text[:300]!r}"
        ) from exc
    session_id = data.get("sessionId")
    if not session_id:
        status = data.get("statusText") or data.get("status") or data
        raise LoginError(f"Login did not return sessionId: {status}")
    return session_id


def _fetch_config(session_id: str, client: httpx.Client) -> dict:
    resp = client.get(ep.BASE_URL + ep.CONFIG_PATH, headers=_auth_headers(session_id))
    resp.raise_for_status()
    return resp.json()["data"]


def _fetch_client_info(session_id: str, pa_url: str, client: httpx.Client) -> dict:
    resp = client.get(
        f"{pa_url}{ep.CLIENT_INFO_PATH}",
        params={"sessionId": session_id},
        headers=_auth_headers(session_id),
    )
    resp.raise_for_status()
    return resp.json()["data"]

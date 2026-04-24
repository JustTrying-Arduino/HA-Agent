"""HTTP client with automatic relogin on session expiry."""

from __future__ import annotations

from typing import Any

import httpx

from . import endpoints as ep
from .session import SessionManager


class DegiroHTTP:
    def __init__(self, session_mgr: SessionManager) -> None:
        self._session = session_mgr
        self._client = httpx.Client(timeout=30.0, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DegiroHTTP":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        content: str | bytes | None = None,
    ) -> httpx.Response:
        state = self._session.require()
        resp = self._raw_request(
            method, url, state.session_id, params=params, json=json, content=content
        )
        if self._needs_relogin(resp):
            self._session.invalidate()
            state = self._session.require()
            resp = self._raw_request(
                method,
                url,
                state.session_id,
                params=params,
                json=json,
                content=content,
            )
        resp.raise_for_status()
        self._session.touch()
        return resp

    def _raw_request(
        self,
        method: str,
        url: str,
        session_id: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        content: str | bytes | None = None,
    ) -> httpx.Response:
        headers = {
            "Cookie": f"JSESSIONID={session_id};",
            "Referer": ep.REFERER,
            "Origin": "https://trader.degiro.nl",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": ep.USER_AGENT,
        }
        if json is not None or content is not None:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        return self._client.request(
            method,
            url,
            params=params,
            json=json,
            content=content,
            headers=headers,
        )

    @staticmethod
    def _needs_relogin(resp: httpx.Response) -> bool:
        if resp.status_code == 401:
            return True
        if resp.status_code in (302, 307) and "login" in resp.headers.get(
            "location", ""
        ):
            return True
        return False

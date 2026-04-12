"""Home Assistant Supervisor API client with label-based entity filtering."""

import ast
import logging
import time

import aiohttp

from agent.config import cfg

BASE_URL = "http://supervisor/core/api"
CACHE_TTL_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 15

logger = logging.getLogger(__name__)

_client: "HAClient | None" = None


class HAClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._labeled_entities_cache: list[str] = []
        self._labeled_entities_cache_until: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
            headers = {
                "Authorization": f"Bearer {cfg.supervisor_token}",
                "Content-Type": "application/json",
            }
            self._session = aiohttp.ClientSession(
                base_url=BASE_URL,
                headers=headers,
                timeout=timeout,
            )
        return self._session

    async def get_labeled_entities(self) -> list[str]:
        now = time.time()
        if now < self._labeled_entities_cache_until:
            logger.debug(
                "Using cached Home Assistant label '%s' (%d entities)",
                cfg.ha_expose_label,
                len(self._labeled_entities_cache),
            )
            return list(self._labeled_entities_cache)

        session = await self._get_session()
        label = cfg.ha_expose_label.replace("\\", "\\\\").replace("'", "\\'")
        template = "{{ label_entities('" + label + "') | list }}"
        logger.debug("Refreshing Home Assistant label '%s' from Supervisor", cfg.ha_expose_label)

        async with session.post("/api/template", json={"template": template}) as resp:
            text = await resp.text()
            if resp.status >= 400:
                logger.warning("Failed to resolve HA label '%s': %s", cfg.ha_expose_label, text)
                entities: list[str] = []
            else:
                entities = self._parse_entity_list(text)

        self._labeled_entities_cache = entities
        self._labeled_entities_cache_until = now + CACHE_TTL_SECONDS
        logger.debug(
            "Loaded %d exposed Home Assistant entities for label '%s'",
            len(entities),
            cfg.ha_expose_label,
        )
        return list(entities)

    async def entity_allowed(self, entity_id: str) -> bool:
        return entity_id in await self.get_labeled_entities()

    async def get_states(self) -> list[dict]:
        session = await self._get_session()
        logger.debug("Fetching all Home Assistant states")
        async with session.get("/api/states") as resp:
            return await self._read_json_response(resp)

    async def get_state(self, entity_id: str) -> dict:
        session = await self._get_session()
        logger.debug("Fetching Home Assistant state for %s", entity_id)
        async with session.get(f"/api/states/{entity_id}") as resp:
            return await self._read_json_response(resp, entity_id=entity_id)

    async def call_service(self, domain: str, service: str, data: dict) -> list[dict] | dict | str:
        session = await self._get_session()
        logger.debug("Calling Home Assistant service %s.%s with payload=%s", domain, service, data)
        async with session.post(f"/api/services/{domain}/{service}", json=data) as resp:
            return await self._read_json_response(resp, entity_id=data.get("entity_id"))

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            logger.debug("Closing Home Assistant Supervisor session")
            await self._session.close()
        self._session = None

    @staticmethod
    def _parse_entity_list(text: str) -> list[str]:
        payload = (text or "").strip()
        if not payload:
            return []

        try:
            parsed = ast.literal_eval(payload)
        except (SyntaxError, ValueError):
            logger.warning("Invalid HA template response for label entities: %r", payload)
            return []

        if not isinstance(parsed, list):
            logger.warning("Unexpected HA template response type: %r", type(parsed).__name__)
            return []

        return [item for item in parsed if isinstance(item, str)]

    async def _read_json_response(
        self,
        resp: aiohttp.ClientResponse,
        entity_id: str | None = None,
    ) -> list[dict] | dict | str:
        if resp.status == 404 and entity_id:
            raise RuntimeError(f"Entity not found: {entity_id}")

        if resp.status >= 400:
            raise RuntimeError(await self._extract_error_message(resp, entity_id=entity_id))

        if resp.content_type == "application/json":
            return await resp.json()

        return await resp.text()

    async def _extract_error_message(
        self,
        resp: aiohttp.ClientResponse,
        entity_id: str | None = None,
    ) -> str:
        body_text = await resp.text()

        if resp.status == 404 and entity_id:
            return f"Entity not found: {entity_id}"

        message = ""
        try:
            data = ast.literal_eval(body_text) if body_text and resp.content_type != "application/json" else None
        except (SyntaxError, ValueError):
            data = None

        if resp.content_type == "application/json":
            try:
                data = await resp.json()
            except Exception:
                data = None

        if isinstance(data, dict):
            for key in ("message", "error", "result"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    message = value.strip()
                    break

        if resp.status == 400 and message:
            return message

        if message:
            return f"Home Assistant API error ({resp.status}): {message}"

        fallback = body_text.strip() or resp.reason or "Unknown error"
        if resp.status == 400:
            return fallback
        return f"Home Assistant API error ({resp.status}): {fallback}"


def get_client() -> HAClient:
    global _client
    if _client is None:
        _client = HAClient()
    return _client


async def close() -> None:
    global _client
    if _client is None:
        return
    await _client.close()
    _client = None

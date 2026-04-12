import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    sys.modules["aiohttp"] = types.SimpleNamespace(
        ClientSession=object,
        ClientTimeout=lambda total=None: None,
        ClientResponse=object,
    )

from agent.ha_client import HAClient  # noqa: E402


class _FakeResponse:
    def __init__(self, status: int, text: str, content_type: str = "text/plain"):
        self.status = status
        self._text = text
        self.content_type = content_type
        self.reason = "error"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self._text

    async def json(self):
        raise AssertionError("json() should not be called in this test")


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.post_calls: list[tuple[str, dict]] = []

    def post(self, path: str, json: dict):
        self.post_calls.append((path, json))
        return self._responses.pop(0)


class HAClientTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_entity_list(self):
        self.assertEqual(
            HAClient._parse_entity_list("['light.kitchen', 'switch.fan']"),
            ["light.kitchen", "switch.fan"],
        )
        self.assertEqual(HAClient._parse_entity_list(""), [])
        with self.assertLogs("agent.ha_client", level="WARNING"):
            self.assertEqual(HAClient._parse_entity_list("not a python list"), [])
        with self.assertLogs("agent.ha_client", level="WARNING"):
            self.assertEqual(HAClient._parse_entity_list("{'entity_id': 'light.kitchen'}"), [])

    async def test_labeled_entities_cache_ttl(self):
        client = HAClient()
        session = _FakeSession(
            [
                _FakeResponse(200, "['light.kitchen']"),
                _FakeResponse(200, "['switch.fan']"),
            ]
        )

        with patch.object(client, "_get_session", AsyncMock(return_value=session)):
            with patch("agent.ha_client.time.time", side_effect=[1000.0, 1001.0, 1062.0]):
                first = await client.get_labeled_entities()
                second = await client.get_labeled_entities()
                third = await client.get_labeled_entities()

        self.assertEqual(first, ["light.kitchen"])
        self.assertEqual(second, ["light.kitchen"])
        self.assertEqual(third, ["switch.fan"])
        self.assertEqual(len(session.post_calls), 2)

    async def test_entity_allowed_uses_cached_entities(self):
        client = HAClient()
        client._labeled_entities_cache = ["light.kitchen", "switch.fan"]
        client._labeled_entities_cache_until = 999999.0

        with patch("agent.ha_client.time.time", return_value=1000.0):
            self.assertTrue(await client.entity_allowed("light.kitchen"))
            self.assertFalse(await client.entity_allowed("sensor.outdoor"))

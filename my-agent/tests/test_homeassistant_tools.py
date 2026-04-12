import importlib
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

from agent.config import cfg  # noqa: E402


class HomeAssistantToolsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_supervisor_token = cfg.supervisor_token
        cfg.supervisor_token = "test-supervisor-token"
        import agent.tools.homeassistant as homeassistant_tools  # noqa: E402

        cls.homeassistant_tools = importlib.reload(homeassistant_tools)

    @classmethod
    def tearDownClass(cls):
        cfg.supervisor_token = cls._original_supervisor_token

    async def test_search_entities_filters_by_label_domain_and_query(self):
        client = type("FakeClient", (), {})()
        client.get_labeled_entities = AsyncMock(
            return_value=["light.kitchen", "switch.fan", "sensor.outdoor_temp"]
        )
        client.get_states = AsyncMock(
            return_value=[
                {
                    "entity_id": "light.kitchen",
                    "state": "on",
                    "attributes": {"friendly_name": "Kitchen Light"},
                },
                {
                    "entity_id": "switch.fan",
                    "state": "off",
                    "attributes": {"friendly_name": "Bedroom Fan"},
                },
                {
                    "entity_id": "sensor.outdoor_temp",
                    "state": "18",
                    "attributes": {
                        "friendly_name": "Outdoor Temperature",
                        "unit_of_measurement": "degC",
                    },
                },
                {
                    "entity_id": "light.hidden",
                    "state": "on",
                    "attributes": {"friendly_name": "Hidden Light"},
                },
            ]
        )

        with patch.object(self.homeassistant_tools, "get_client", return_value=client):
            result = await self.homeassistant_tools.ha_search_entities(
                query="kitchen",
                domain="light",
                limit=5,
            )

        self.assertEqual(result, "light.kitchen | Kitchen Light | on")

    async def test_get_state_refuses_non_exposed_entity(self):
        client = type("FakeClient", (), {})()
        client.entity_allowed = AsyncMock(return_value=False)

        with patch.object(self.homeassistant_tools, "get_client", return_value=client):
            result = await self.homeassistant_tools.ha_get_state("light.secret")

        self.assertEqual(result, "Error: entity 'light.secret' is not exposed to the agent.")

    async def test_call_service_builds_payload_and_summarizes_result(self):
        client = type("FakeClient", (), {})()
        client.entity_allowed = AsyncMock(return_value=True)
        client.call_service = AsyncMock(
            return_value=[
                {
                    "entity_id": "light.kitchen",
                    "state": "on",
                    "attributes": {"friendly_name": "Kitchen Light", "brightness": 200},
                }
            ]
        )

        with patch.object(self.homeassistant_tools, "get_client", return_value=client):
            result = await self.homeassistant_tools.ha_call_service(
                domain="light",
                service="turn_on",
                entity_id="light.kitchen",
                service_data={"brightness": 200},
            )

        client.call_service.assert_awaited_once_with(
            "light",
            "turn_on",
            {"entity_id": "light.kitchen", "brightness": 200},
        )
        self.assertIn("Service called: light.turn_on on light.kitchen", result)
        self.assertIn("light.kitchen | Kitchen Light | on", result)

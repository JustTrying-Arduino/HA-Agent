import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import db  # noqa: E402
from agent.config import cfg  # noqa: E402

try:
    from aiohttp.test_utils import TestClient, TestServer
    from agent.server import create_app  # noqa: E402
    HAS_AIOHTTP = True
except ModuleNotFoundError:
    HAS_AIOHTTP = False


@unittest.skipUnless(HAS_AIOHTTP, "aiohttp test dependencies are not installed")
class ServerApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = cfg.db_path
        cfg.db_path = str(Path(self.tmpdir.name) / "agent.db")
        db.close()
        db.init_db()

        self.server = TestServer(create_app())
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        db.close()
        cfg.db_path = self.old_db_path
        self.tmpdir.cleanup()

    def _insert_message(self, *, chat_id: int, role: str, content: str, timestamp: str):
        db.execute(
            "INSERT INTO messages (chat_id, role, content, timestamp, archived, model) "
            "VALUES (?, ?, ?, ?, 0, NULL)",
            (chat_id, role, content, timestamp),
        )
        db.commit()

    def _insert_tool_call(
        self,
        *,
        chat_id: int,
        tool_name: str,
        timestamp: str,
        input_summary: str = "{}",
        output_summary: str = "ok",
        success: bool = True,
        duration_ms: int = 10,
    ):
        db.execute(
            "INSERT INTO tool_calls (timestamp, chat_id, message_id, tool_name, input_summary, output_summary, success, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (timestamp, chat_id, None, tool_name, input_summary, output_summary, int(success), duration_ms),
        )
        db.commit()

    async def test_api_chats_returns_known_chats_sorted_by_last_activity(self):
        self._insert_message(
            chat_id=111,
            role="user",
            content="hello",
            timestamp="2026-04-10T10:00:00Z",
        )
        self._insert_tool_call(
            chat_id=222,
            tool_name="web_search",
            timestamp="2026-04-10T12:00:00Z",
        )
        self._insert_message(
            chat_id=333,
            role="user",
            content="latest",
            timestamp="2026-04-10T11:00:00Z",
        )

        response = await self.client.get("/api/chats")
        self.assertEqual(response.status, 200)
        payload = await response.json()

        self.assertEqual(
            payload["chats"],
            [
                {"chat_id": 222, "last_activity": "2026-04-10T12:00:00Z"},
                {"chat_id": 333, "last_activity": "2026-04-10T11:00:00Z"},
                {"chat_id": 111, "last_activity": "2026-04-10T10:00:00Z"},
            ],
        )

    async def test_api_tool_calls_filters_by_chat_id(self):
        self._insert_tool_call(
            chat_id=111,
            tool_name="read_file",
            timestamp="2026-04-10T10:00:00Z",
        )
        self._insert_tool_call(
            chat_id=222,
            tool_name="exec",
            timestamp="2026-04-10T11:00:00Z",
        )

        response = await self.client.get("/api/tool_calls?chat_id=222&limit=50")
        self.assertEqual(response.status, 200)
        payload = await response.json()

        self.assertEqual(len(payload["tool_calls"]), 1)
        self.assertEqual(payload["tool_calls"][0]["chat_id"], 222)
        self.assertEqual(payload["tool_calls"][0]["tool_name"], "exec")

    async def test_api_messages_without_chat_filter_keeps_tool_calls_for_each_chat(self):
        self._insert_message(
            chat_id=111,
            role="assistant",
            content="assistant in chat 111",
            timestamp="2026-04-10T10:05:40Z",
        )
        self._insert_message(
            chat_id=222,
            role="assistant",
            content="assistant in chat 222",
            timestamp="2026-04-10T10:05:20Z",
        )
        self._insert_tool_call(
            chat_id=111,
            tool_name="read_file",
            timestamp="2026-04-10T10:05:05Z",
            output_summary="chat 111 tool",
        )
        self._insert_tool_call(
            chat_id=222,
            tool_name="web_search",
            timestamp="2026-04-10T10:05:15Z",
            output_summary="chat 222 tool",
        )
        self._insert_tool_call(
            chat_id=333,
            tool_name="exec",
            timestamp="2026-04-10T10:05:25Z",
            output_summary="chat 333 tool",
        )

        response = await self.client.get("/api/messages?limit=50")
        self.assertEqual(response.status, 200)
        payload = await response.json()

        returned_tool_calls = payload["tool_calls"]
        returned_chat_ids = {item["chat_id"] for item in returned_tool_calls}

        self.assertEqual(returned_chat_ids, {111, 222})
        self.assertEqual(len(returned_tool_calls), 2)
        self.assertNotIn(333, returned_chat_ids)


if __name__ == "__main__":
    unittest.main()

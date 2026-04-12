import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import db  # noqa: E402
from agent.config import cfg  # noqa: E402
from agent.memory import expire_session_if_needed, get_session_messages, save_message  # noqa: E402


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = cfg.db_path
        self.original_timeout = cfg.session_timeout_hours
        self.original_max_messages = cfg.max_session_messages
        cfg.db_path = str(Path(self.tmpdir.name) / "agent.db")
        cfg.session_timeout_hours = 48
        cfg.max_session_messages = 15
        db.close()
        db.init_db()

    def tearDown(self):
        db.close()
        cfg.db_path = self.original_db_path
        cfg.session_timeout_hours = self.original_timeout
        cfg.max_session_messages = self.original_max_messages
        self.tmpdir.cleanup()

    def _insert_message(self, *, chat_id: int, role: str, content: str, timestamp: str, archived: int = 0):
        db.execute(
            "INSERT INTO messages (chat_id, role, content, timestamp, archived, model) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (chat_id, role, content, timestamp, archived),
        )
        db.commit()

    def test_expire_session_if_needed_archives_stale_messages(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        self._insert_message(chat_id=123, role="user", content="old", timestamp=old_ts)

        expired = expire_session_if_needed(123)
        archived_rows = db.fetchall(
            "SELECT archived FROM messages WHERE chat_id = ? ORDER BY id",
            (123,),
        )

        self.assertTrue(expired)
        self.assertEqual([row["archived"] for row in archived_rows], [1])
        self.assertEqual(get_session_messages(123), [])

    def test_recent_message_keeps_session_active(self):
        recent_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self._insert_message(chat_id=456, role="assistant", content="still active", timestamp=recent_ts)

        expired = expire_session_if_needed(456)

        self.assertFalse(expired)
        self.assertEqual(
            get_session_messages(456),
            [{"role": "assistant", "content": "still active"}],
        )

    def test_new_message_after_timeout_starts_a_fresh_session(self):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        self._insert_message(chat_id=654, role="user", content="old", timestamp=old_ts)

        self.assertTrue(expire_session_if_needed(654))
        save_message(654, "user", "new")

        rows = db.fetchall(
            "SELECT content, archived FROM messages WHERE chat_id = ? ORDER BY id",
            (654,),
        )

        self.assertEqual(
            [(row["content"], row["archived"]) for row in rows],
            [("old", 1), ("new", 0)],
        )
        self.assertEqual(
            get_session_messages(654),
            [{"role": "user", "content": "new"}],
        )

    def test_get_session_messages_applies_configured_window(self):
        cfg.max_session_messages = 3

        for idx in range(5):
            save_message(789, "user", f"msg-{idx}")

        self.assertEqual(
            get_session_messages(789),
            [
                {"role": "user", "content": "msg-2"},
                {"role": "user", "content": "msg-3"},
                {"role": "user", "content": "msg-4"},
            ],
        )


if __name__ == "__main__":
    unittest.main()

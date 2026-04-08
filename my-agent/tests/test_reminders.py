import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import db, reminders  # noqa: E402
from agent.config import cfg  # noqa: E402


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = cfg.db_path
        self.original_timezone = cfg.timezone
        cfg.db_path = str(Path(self.tmpdir.name) / "agent.db")
        cfg.timezone = "Europe/Paris"
        db.close()
        db.init_db()

    def tearDown(self):
        db.close()
        cfg.db_path = self.original_db_path
        cfg.timezone = self.original_timezone
        self.tmpdir.cleanup()

    def test_create_once_reminder(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).astimezone(
            reminders.get_timezone("Europe/Paris")
        )
        reminder = reminders.create_reminder(
            chat_id=123,
            title="Fermer le garage",
            instruction="Rappelle-moi de fermer le garage",
            schedule_kind="once",
            run_at=future.strftime("%Y-%m-%d %H:%M"),
            timezone_name="Europe/Paris",
        )

        self.assertEqual(reminder["status"], reminders.STATUS_ACTIVE)
        self.assertEqual(reminder["schedule_kind"], "once")
        self.assertIsNotNone(reminder["next_run_at"])

        rows = reminders.list_reminders(chat_id=123, status="active")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Fermer le garage")

    def test_recurring_update_and_cancel(self):
        reminder = reminders.create_reminder(
            chat_id=321,
            title="Meteo",
            instruction="Donne-moi la meteo",
            schedule_kind="recurring",
            cron_expr="0 8 * * 1",
            timezone_name="Europe/Paris",
        )

        updated = reminders.update_reminder(
            chat_id=321,
            reminder_id=reminder["id"],
            title="Meteo mardi",
            cron_expr="30 9 * * 2",
        )
        self.assertEqual(updated["title"], "Meteo mardi")
        self.assertEqual(updated["schedule_expr"], "30 9 * * 2")

        cancelled = reminders.cancel_reminder(chat_id=321, reminder_id=reminder["id"])
        self.assertEqual(cancelled["status"], reminders.STATUS_CANCELLED)
        self.assertIsNone(cancelled["next_run_at"])
        self.assertIsNotNone(cancelled["archived_at"])

    def test_purge_cancelled_reminder(self):
        reminder = reminders.create_reminder(
            chat_id=654,
            title="Annule-moi",
            instruction="Test cancel",
            schedule_kind="recurring",
            cron_expr="0 8 * * *",
            timezone_name="UTC",
        )

        cancelled = reminders.cancel_reminder(chat_id=654, reminder_id=reminder["id"])
        self.assertEqual(cancelled["status"], reminders.STATUS_CANCELLED)

        old_time = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        db.execute(
            "UPDATE reminders SET archived_at = ?, updated_at = ? WHERE id = ?",
            (old_time, old_time, reminder["id"]),
        )
        db.commit()

        deleted = reminders.purge_archived_reminders()
        self.assertEqual(deleted, 1)
        self.assertEqual(reminders.list_reminders(chat_id=654, status="cancelled"), [])

    def test_archive_and_purge_once_reminder(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        reminder = reminders.create_reminder(
            chat_id=456,
            title="Test",
            instruction="Run test",
            schedule_kind="once",
            run_at=future.isoformat(),
            timezone_name="UTC",
        )

        archived = reminders.mark_executed(reminder, error="boom")
        self.assertEqual(archived["status"], reminders.STATUS_ARCHIVED)
        self.assertEqual(archived["last_error"], "boom")

        old_time = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        db.execute(
            "UPDATE reminders SET archived_at = ?, updated_at = ? WHERE id = ?",
            (old_time, old_time, reminder["id"]),
        )
        db.commit()

        deleted = reminders.purge_archived_reminders()
        self.assertEqual(deleted, 1)
        self.assertEqual(reminders.list_reminders(chat_id=456, status="archived"), [])


if __name__ == "__main__":
    unittest.main()

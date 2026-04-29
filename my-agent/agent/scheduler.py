"""Internal reminder scheduler."""

from __future__ import annotations

import asyncio
import logging

from agent import orders
from agent.loop import run_agent
from agent.reminders import get_due_reminders, mark_executed, purge_archived_reminders
from agent.telegram import build_telegram_chunks, _run_telegram_request

logger = logging.getLogger(__name__)

SCHEDULER_POLL_SECONDS = 15


async def send_text(bot, chat_id: int, text: str):
    content = text or "(empty response)"
    chunks = build_telegram_chunks(content)
    for chunk in chunks:
        await _run_telegram_request(
            lambda text, parse_mode=None: bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            ),
            chunk["text"],
            chunk["parse_mode"],
            "Failed to send Telegram scheduler message",
        )


async def process_due_reminders(bot):
    due = get_due_reminders(limit=20)
    for reminder in due:
        error = None
        try:
            logger.info(
                "Triggering reminder id=%s chat_id=%s title=%s",
                reminder["id"],
                reminder["chat_id"],
                reminder["title"],
            )
            context = (
                f"[REMINDER TRIGGER] id=#{reminder['id']} "
                f"title=\"{reminder['title']}\" "
                f"kind={reminder['schedule_kind']}\n"
                f"[REMINDER INSTRUCTION] {reminder['instruction']}"
            )
            response = await run_agent(
                reminder["chat_id"],
                context,
                cron=True,
            )
            await send_text(bot, reminder["chat_id"], response)
        except Exception as exc:
            error = str(exc)
            logger.exception("Reminder execution failed: id=%s", reminder["id"])
            try:
                await send_text(
                    bot,
                    reminder["chat_id"],
                    f"Reminder '{reminder['title']}' failed: {error}",
                )
            except Exception:
                logger.exception("Reminder failure notification failed: id=%s", reminder["id"])
        finally:
            mark_executed(reminder, error=error)


async def expire_pending_orders(bot):
    expired = await asyncio.to_thread(orders.expire_due_pending)
    for row in expired:
        msg_id = row.get("telegram_message_id")
        if msg_id is None:
            continue
        try:
            await bot.edit_message_text(
                chat_id=row["chat_id"],
                message_id=msg_id,
                text=(row.get("preview_text") or "") + "\n\n[Expire]",
                reply_markup=None,
            )
        except Exception:
            logger.exception(
                "Failed to edit expired pending message id=%s", row["id"],
            )


async def run_scheduler(bot):
    while True:
        try:
            await process_due_reminders(bot)
            purge_archived_reminders()
            await expire_pending_orders(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder scheduler iteration failed")
        await asyncio.sleep(SCHEDULER_POLL_SECONDS)

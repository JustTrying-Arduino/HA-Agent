"""Internal reminder scheduler."""

from __future__ import annotations

import asyncio
import logging

from agent.loop import run_agent
from agent.reminders import get_due_reminders, mark_executed, purge_archived_reminders

logger = logging.getLogger(__name__)

SCHEDULER_POLL_SECONDS = 15
MAX_TELEGRAM_MSG = 4096


async def send_text(bot, chat_id: int, text: str):
    content = text or "(empty response)"
    if len(content) <= MAX_TELEGRAM_MSG:
        await bot.send_message(chat_id=chat_id, text=content)
        return

    chunks = []
    current = ""
    for paragraph in content.split("\n\n"):
        if len(current) + len(paragraph) + 2 > MAX_TELEGRAM_MSG:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph

    if current:
        chunks.append(current.strip())

    for chunk in chunks:
        while len(chunk) > MAX_TELEGRAM_MSG:
            await bot.send_message(chat_id=chat_id, text=chunk[:MAX_TELEGRAM_MSG])
            chunk = chunk[MAX_TELEGRAM_MSG:]
        if chunk:
            await bot.send_message(chat_id=chat_id, text=chunk)


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


async def run_scheduler(bot):
    while True:
        try:
            await process_due_reminders(bot)
            purge_archived_reminders()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder scheduler iteration failed")
        await asyncio.sleep(SCHEDULER_POLL_SECONDS)

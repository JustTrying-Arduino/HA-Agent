"""Telegram bot: polling, message dispatch (text + audio)."""

import os
import tempfile
import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from agent.config import cfg
from agent.loop import run_agent
from agent.tools.audio import transcribe_audio

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MSG = 4096


def start_bot() -> Application:
    """Create and return the Telegram Application (do NOT call run_polling)."""
    app = Application.builder().token(cfg.telegram_bot_token).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO, handle_message))
    return app


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Check authorization
    if cfg.telegram_allowed_chat_ids and chat_id not in cfg.telegram_allowed_chat_ids:
        logger.warning("Unauthorized message from chat_id=%s", chat_id)
        return

    # Extract text (or transcribe audio)
    if update.message.voice or update.message.audio:
        text = await _handle_audio(update)
        if text is None:
            await update.message.reply_text("Failed to transcribe audio message.")
            return
    elif update.message.text:
        text = update.message.text
    else:
        return

    logger.info("Incoming message from chat_id=%s: %s", chat_id, text[:100])

    # Run agent
    response = await run_agent(chat_id, text)

    logger.info("Outgoing message to chat_id=%s: %s", chat_id, response[:100])

    # Send response (split if too long)
    await _send_response(update, response)


async def _handle_audio(update: Update) -> str | None:
    """Download and transcribe a voice/audio message."""
    if not cfg.groq_api_key:
        logger.warning("Groq API key not set, cannot transcribe audio")
        return None

    try:
        voice = update.message.voice or update.message.audio
        file = await voice.get_file()

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        await file.download_to_drive(tmp_path)
        text = transcribe_audio(tmp_path)
        os.unlink(tmp_path)

        return f"[Message vocal transcrit] {text}"
    except Exception as e:
        logger.exception("Audio transcription failed")
        return None


async def _send_response(update: Update, text: str):
    """Send a response, splitting into chunks if needed."""
    if len(text) <= MAX_TELEGRAM_MSG:
        await update.message.reply_text(text)
        return

    # Split on paragraph boundaries
    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > MAX_TELEGRAM_MSG:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph

    if current:
        chunks.append(current.strip())

    # Fallback: split on hard limit if a single paragraph exceeds limit
    final_chunks = []
    for chunk in chunks:
        while len(chunk) > MAX_TELEGRAM_MSG:
            final_chunks.append(chunk[:MAX_TELEGRAM_MSG])
            chunk = chunk[MAX_TELEGRAM_MSG:]
        if chunk:
            final_chunks.append(chunk)

    for chunk in final_chunks:
        await update.message.reply_text(chunk)

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
INITIAL_STATUS_TEXT = "En reflexion..."
DEFAULT_TOOL_STATUS = "Traitement en cours..."
STATUS_TOOLS = {
    "read_file",
    "write_file",
    "edit_file",
    "web_search",
    "web_fetch",
    "exec",
    "ha_search_entities",
    "ha_get_state",
    "ha_call_service",
}
TOOL_STATUS_LABELS = {
    "read_file": "Lecture de fichier...",
    "write_file": "Ecriture de fichier...",
    "edit_file": "Modification de fichier...",
    "list_dir": "Exploration du dossier...",
    "web_search": "Recherche web...",
    "web_fetch": "Lecture d'une page web...",
    "exec": "Execution d'une commande...",
    "ha_search_entities": "Recherche dans Home Assistant...",
    "ha_get_state": "Lecture Home Assistant...",
    "ha_call_service": "Commande Home Assistant...",
    "create_reminder": "Creation du rappel...",
    "list_reminders": "Consultation des rappels...",
    "update_reminder": "Mise a jour du rappel...",
    "cancel_reminder": "Annulation du rappel...",
}


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

    if not (update.message.text or update.message.voice or update.message.audio):
        return

    status_message = await update.message.reply_text(INITIAL_STATUS_TEXT)
    progress_callback, progress_state = _build_progress_callback(status_message)

    # Extract text (or transcribe audio)
    if update.message.voice or update.message.audio:
        text = await _handle_audio(update)
        if text is None:
            await _safe_edit_message(status_message, progress_state, "Failed to transcribe audio message.")
            return
    elif update.message.text:
        text = update.message.text
    else:
        return

    logger.info("Incoming message from chat_id=%s: %s", chat_id, text[:100])

    # Run agent
    response = await run_agent(chat_id, text, progress_callback=progress_callback)

    logger.info("Outgoing message to chat_id=%s: %s", chat_id, response[:100])

    # Send response (split if too long)
    await _finalize_response(update, status_message, progress_state, response)


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


def _build_progress_callback(status_message):
    state = {
        "current_text": INITIAL_STATUS_TEXT,
    }

    async def progress_callback(event: str, payload: dict):
        if event == "tool_start":
            tool_name = payload.get("tool_name")
            if tool_name in STATUS_TOOLS:
                await _safe_edit_message(status_message, state, _tool_status_text(tool_name))

    return progress_callback, state


def _tool_status_text(tool_name: str | None) -> str:
    label = TOOL_STATUS_LABELS.get(tool_name or "", DEFAULT_TOOL_STATUS)
    return f"Outil en cours : {label}"


async def _safe_edit_message(message, state: dict, text: str):
    current = state.get("current_text")
    if current == text:
        return

    try:
        await message.edit_text(text)
        state["current_text"] = text
    except Exception:
        logger.exception("Failed to edit Telegram status message")


async def _safe_delete_message(message):
    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete Telegram status message")


async def _finalize_response(update: Update, status_message, state: dict, text: str):
    content = text or "(empty response)"

    if len(content) <= MAX_TELEGRAM_MSG:
        await _safe_edit_message(status_message, state, content)
        return

    await _safe_delete_message(status_message)
    await _send_response(update, content)

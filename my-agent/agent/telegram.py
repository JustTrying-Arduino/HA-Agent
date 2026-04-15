"""Telegram bot: polling, message dispatch (text + audio)."""

from html import unescape
import os
import tempfile
import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from agent.config import cfg
from agent.loop import run_agent
from agent.tools.audio import transcribe_audio

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MSG = 4096
INITIAL_STATUS_TEXT = "En reflexion..."
DEFAULT_TOOL_STATUS = "Traitement en cours..."
SUPPORTED_HTML_TAG_RE = re.compile(
    r"</?(?:b|i|code|pre)\s*>|<a\s+href=\"[^\"]*\">|</a>",
    re.IGNORECASE,
)
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


def _prepare_formatted_response(text: str) -> dict[str, str | None]:
    html_text = text or ""
    return {
        "html_text": html_text,
        "plain_text": _strip_supported_html(html_text),
        "parse_mode": ParseMode.HTML,
    }


def _strip_supported_html(text: str) -> str:
    return unescape(SUPPORTED_HTML_TAG_RE.sub("", text or ""))


def _contains_supported_html(text: str) -> bool:
    return bool(SUPPORTED_HTML_TAG_RE.search(text or ""))


def _split_html_blocks(text: str) -> list[str]:
    if not text:
        return []

    blocks: list[str] = []
    current: list[str] = []
    i = 0
    lowered = text.lower()
    in_pre = False

    while i < len(text):
        if lowered.startswith("<pre>", i):
            in_pre = True
            current.append(text[i:i + 5])
            i += 5
            continue
        if lowered.startswith("</pre>", i):
            in_pre = False
            current.append(text[i:i + 6])
            i += 6
            continue
        if not in_pre and text.startswith("\n\n", i):
            blocks.append("".join(current))
            current = []
            i += 2
            continue

        current.append(text[i])
        i += 1

    blocks.append("".join(current))
    return blocks


def _split_plain_text(text: str) -> list[str]:
    return [text[i:i + MAX_TELEGRAM_MSG] for i in range(0, len(text), MAX_TELEGRAM_MSG)] or [""]


def build_telegram_chunks(text: str) -> list[dict[str, str | None]]:
    prepared = _prepare_formatted_response(text)
    blocks = _split_html_blocks(prepared["html_text"])
    if not blocks:
        return []

    chunks: list[dict[str, str | None]] = []
    current_html = ""

    for block in blocks:
        if len(block) <= MAX_TELEGRAM_MSG:
            candidate = f"{current_html}\n\n{block}" if current_html else block
            if current_html and len(candidate) > MAX_TELEGRAM_MSG:
                chunks.append({"text": current_html, "parse_mode": ParseMode.HTML})
                current_html = block
            else:
                current_html = candidate
            continue

        if current_html:
            chunks.append({"text": current_html, "parse_mode": ParseMode.HTML})
            current_html = ""

        plain_block = _strip_supported_html(block)
        source = plain_block if _contains_supported_html(block) else block
        for part in _split_plain_text(source):
            chunks.append({"text": part, "parse_mode": None})

    if current_html:
        chunks.append({"text": current_html, "parse_mode": ParseMode.HTML})

    return chunks


async def _run_telegram_request(send_func, text: str, parse_mode: str | None, action_label: str) -> tuple[str, str | None]:
    try:
        await send_func(text=text, parse_mode=parse_mode)
        return text, parse_mode
    except Exception:
        if parse_mode == ParseMode.HTML:
            logger.warning("%s failed with HTML, retrying as plain text", action_label, exc_info=True)
            fallback_text = _strip_supported_html(text)
            await send_func(text=fallback_text, parse_mode=None)
            return fallback_text, None
        raise


async def _send_response(update: Update, chunks: list[dict[str, str | None]]):
    """Send prepared response chunks."""
    for chunk in chunks:
        await _run_telegram_request(
            lambda text, parse_mode=None: update.message.reply_text(text, parse_mode=parse_mode),
            chunk["text"],
            chunk["parse_mode"],
            "Failed to send Telegram reply",
        )


def _build_progress_callback(status_message):
    state = {
        "current_text": INITIAL_STATUS_TEXT,
        "current_parse_mode": None,
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


async def _safe_edit_message(message, state: dict, text: str, parse_mode: str | None = None):
    current = state.get("current_text")
    current_parse_mode = state.get("current_parse_mode")
    if current == text and current_parse_mode == parse_mode:
        return

    try:
        rendered_text, rendered_parse_mode = await _run_telegram_request(
            lambda text, parse_mode=None: message.edit_text(text, parse_mode=parse_mode),
            text,
            parse_mode,
            "Failed to edit Telegram message",
        )
        state["current_text"] = rendered_text
        state["current_parse_mode"] = rendered_parse_mode
    except Exception:
        logger.exception("Failed to edit Telegram status message")


async def _safe_delete_message(message):
    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete Telegram status message")


async def _finalize_response(update: Update, status_message, state: dict, text: str):
    if not text or not text.strip():
        await _safe_delete_message(status_message)
        return

    chunks = build_telegram_chunks(text)
    if len(chunks) == 1:
        chunk = chunks[0]
        await _safe_edit_message(status_message, state, chunk["text"], parse_mode=chunk["parse_mode"])
        return

    await _safe_delete_message(status_message)
    await _send_response(update, chunks)

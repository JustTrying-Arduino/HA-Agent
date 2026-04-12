"""Session management and logging helpers (SQLite-backed)."""

import time
import logging
from datetime import datetime, timezone

from agent.config import cfg
from agent import db

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def expire_session_if_needed(chat_id: int) -> bool:
    """Archive the active session if the last message is older than the timeout."""
    row = db.fetchone(
        "SELECT timestamp FROM messages "
        "WHERE chat_id = ? AND archived = 0 "
        "ORDER BY timestamp DESC LIMIT 1",
        (chat_id,),
    )

    if row is None:
        return False

    last_ts = datetime.fromisoformat(row["timestamp"]).timestamp()
    if time.time() - last_ts <= cfg.session_timeout_hours * 3600:
        return False

    archive_session(chat_id)
    logger.info("Session archived for chat_id=%s (timeout)", chat_id)
    return True


def get_session_messages(chat_id: int) -> list[dict]:
    """Return active session messages for a chat, applying timeout and window rules."""
    if expire_session_if_needed(chat_id):
        return []

    rows = db.fetchall(
        "SELECT role, content, timestamp FROM messages "
        "WHERE chat_id = ? AND archived = 0 ORDER BY timestamp",
        (chat_id,),
    )

    if not rows:
        return []

    # Keep only the last N messages in the active session.
    messages = [{"role": r["role"], "content": r["content"]} for r in rows]
    return messages[-cfg.max_session_messages :]


def archive_session(chat_id: int):
    """Mark all non-archived messages for a chat as archived."""
    db.execute(
        "UPDATE messages SET archived = 1 WHERE chat_id = ? AND archived = 0",
        (chat_id,),
    )
    db.commit()


def save_message(chat_id: int, role: str, content: str, model: str | None = None):
    """Save a message to the session history."""
    db.execute(
        "INSERT INTO messages (chat_id, role, content, timestamp, archived, model) VALUES (?, ?, ?, ?, 0, ?)",
        (chat_id, role, content, _now_iso(), model),
    )
    db.commit()


def log_token_usage(chat_id: int, model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0):
    """Log token usage for a request."""
    db.execute(
        "INSERT INTO token_usage (timestamp, chat_id, model, input_tokens, output_tokens, cached_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_now_iso(), chat_id, model, input_tokens, output_tokens, cached_tokens),
    )
    db.commit()
    logger.info(
        "Tokens consumed: model=%s in=%d out=%d cached=%d",
        model, input_tokens, output_tokens, cached_tokens,
    )


def get_recent_tool_calls(chat_id: int, limit: int = 5) -> list[dict]:
    """Return the most recent tool calls for a chat (newest first)."""
    rows = db.fetchall(
        "SELECT tool_name, input_summary, success, duration_ms, timestamp "
        "FROM tool_calls WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?",
        (chat_id, limit),
    )
    return [dict(r) for r in rows]


def log_tool_call(
    chat_id: int, message_id: str, tool_name: str,
    input_summary: str, output_summary: str, success: bool, duration_ms: int,
):
    """Log a tool call."""
    db.execute(
        "INSERT INTO tool_calls (timestamp, chat_id, message_id, tool_name, input_summary, output_summary, success, duration_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (_now_iso(), chat_id, message_id, tool_name,
         input_summary[:500], output_summary[:500], int(success), duration_ms),
    )
    db.commit()

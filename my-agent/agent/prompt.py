"""System prompt assembly from workspace files."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.config import cfg
from agent.memory import get_recent_tool_calls

logger = logging.getLogger(__name__)


def _read_if_exists(path: Path) -> str | None:
    if path.exists():
        return path.read_text().strip()
    return None


RECENT_TOOLS_MAX_AGE_HOURS = 3


def _format_recent_tools(chat_id: int | None) -> str | None:
    """Format recent tool calls as a compact summary for the system prompt."""
    if chat_id is None:
        return None
    recent = get_recent_tool_calls(chat_id, limit=5)
    if not recent:
        return None

    now = datetime.now(ZoneInfo(cfg.timezone))
    cutoff = now - timedelta(hours=RECENT_TOOLS_MAX_AGE_HOURS)

    lines = []
    for tc in reversed(recent):  # oldest first
        ts = datetime.fromisoformat(tc["timestamp"].replace("Z", "+00:00"))
        ts_local = ts.astimezone(ZoneInfo(cfg.timezone))
        if ts_local < cutoff:
            continue
        status = "ok" if tc["success"] else "FAIL"
        time_str = ts_local.strftime("%Y-%m-%d %H:%M")
        lines.append(f"- [{time_str}] {tc['tool_name']}({tc['input_summary'][:80]}) → {status} [{tc['duration_ms']}ms]")

    if not lines:
        return None
    return "## Recent Tool Calls\n" + "\n".join(lines)


def build_system_prompt(chat_id: int | None = None) -> str:
    """Build the system prompt from AGENT.md, USER.md, skills, and MEMORY.md."""
    ws = Path(cfg.workspace_path)
    parts = []

    try:
        now_local = datetime.now(ZoneInfo(cfg.timezone))
    except ZoneInfoNotFoundError:
        now_local = datetime.utcnow()
    parts.append(
        "## Runtime Context\n"
        f"- Current local time: {now_local.strftime('%Y-%m-%d %H:%M %Z')}\n"
        f"- Default timezone: {cfg.timezone}\n"
        "- Reminders must be managed with dedicated reminder tools, not by editing system files.\n"
        "- Reminder tools available: create_reminder, list_reminders, update_reminder, cancel_reminder.\n"
        "- When a date/time is ambiguous or in the past, ask the user to clarify before creating a reminder."
    )

    if cfg.openai_model_light != cfg.openai_model:
        parts[-1] += (
            f"\n- You are running on the lightweight model ({cfg.openai_model_light}). "
            f"Use escalate_model before any web search/browsing or when the task will likely "
            f"need 2 or more tool calls. Skip escalation for simple one-shot answers."
        )

    agent_md = _read_if_exists(ws / "AGENT.md")
    if agent_md:
        parts.append(agent_md)

    user_md = _read_if_exists(ws / "USER.md")
    if user_md:
        parts.append(f"## User Profile\n{user_md}")

    skills_dir = ws / "skills"
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if skill_dir.is_dir():
                skill_md = _read_if_exists(skill_dir / "SKILL.md")
                if skill_md:
                    parts.append(f"## Skill: {skill_dir.name}\n{skill_md}")

    memory_md = _read_if_exists(ws / "MEMORY.md")
    if memory_md:
        parts.append(f"## Long-term Memory\n{memory_md}")

    recent_tools = _format_recent_tools(chat_id)
    if recent_tools:
        parts.append(recent_tools)

    return "\n\n---\n\n".join(parts)


def build_cron_prompt(chat_id: int | None = None) -> str:
    """Build the system prompt for scheduled reminder executions."""
    base = build_system_prompt(chat_id)
    ws = Path(cfg.workspace_path)
    reminder_md = _read_if_exists(ws / "Prompt_Reminder.md")
    if reminder_md:
        return base + "\n\n---\n\n## Reminder Trigger Instructions\n" + reminder_md
    return base

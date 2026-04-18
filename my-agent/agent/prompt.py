"""System prompt assembly from workspace files."""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent.config import cfg
from agent.memory import get_recent_tool_calls

logger = logging.getLogger(__name__)
SKILL_SUMMARY_MAX_LEN = 160


def _read_if_exists(path: Path) -> str | None:
    if path.exists():
        return path.read_text().strip()
    return None


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_markdown_section(text: str, title: str) -> str | None:
    lines = text.splitlines()
    target = f"## {title}".strip().lower()
    in_section = False
    collected: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.lower() == target:
            in_section = True
            continue
        if in_section and stripped.startswith("#"):
            break
        if in_section:
            collected.append(line)

    section = "\n".join(collected).strip()
    return section or None


def _summarize_skill(skill_md: str) -> str:
    purpose = _extract_markdown_section(skill_md, "Purpose")
    if purpose:
        return _truncate_summary(_collapse_whitespace(purpose))

    use_when = _extract_markdown_section(skill_md, "Use This Skill When")
    if use_when:
        for line in use_when.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                return _truncate_summary(_collapse_whitespace(stripped[2:]))

    for line in skill_md.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        return _truncate_summary(_collapse_whitespace(stripped))

    return "No description available."


def _truncate_summary(text: str) -> str:
    if len(text) <= SKILL_SUMMARY_MAX_LEN:
        return text.rstrip(" .")
    return text[: SKILL_SUMMARY_MAX_LEN - 3].rstrip() + "..."


def _build_skills_index(skills_dir: Path) -> str | None:
    entries: list[str] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        skill_md = _read_if_exists(skill_path)
        if not skill_md:
            continue
        summary = _summarize_skill(skill_md)
        entries.append(
            f"- {skill_dir.name}: {summary}. Read {skill_path} with read_file if needed."
        )

    if not entries:
        return None

    return (
        "## Skills Index\n"
        "- If a task may match a listed skill, read its SKILL.md with read_file before following it.\n"
        "- Do not assume hidden skill details unless the file has been read.\n"
        + "\n".join(entries)
    )


def _read_chat_context(ws: Path, chat_id: int | None) -> str | None:
    if chat_id is None:
        return None

    return _read_if_exists(ws / "chats" / f"{chat_id}.md")


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
        parts.append(f"## AGENT.md\n{agent_md}")

    user_md = _read_if_exists(ws / "USER.md")
    if user_md:
        parts.append(f"## USER.md\n{user_md}")

    chat_context_md = _read_chat_context(ws, chat_id)
    if chat_context_md:
        parts.append(
            "## Current Chat Specific Context\n"
            f"- Current chat ID: {chat_id}\n"
            f"{chat_context_md}"
        )

    skills_dir = ws / "skills"
    if skills_dir.exists():
        skills_index = _build_skills_index(skills_dir)
        if skills_index:
            parts.append(skills_index)

    memory_md = _read_if_exists(ws / "MEMORY.md")
    if memory_md:
        parts.append(f"## MEMORY.md\n{memory_md}")

    if cfg.include_recent_tool_calls:
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
        return base + "\n\n---\n\n## Prompt_Reminder.md\n" + reminder_md
    return base

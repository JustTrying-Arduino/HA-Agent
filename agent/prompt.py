"""System prompt assembly from workspace files."""

import logging
from pathlib import Path

from agent.config import cfg

logger = logging.getLogger(__name__)


def _read_if_exists(path: Path) -> str | None:
    if path.exists():
        return path.read_text().strip()
    return None


def build_system_prompt() -> str:
    """Build the system prompt from AGENT.md, USER.md, skills, and MEMORY.md."""
    ws = Path(cfg.workspace_path)
    parts = []

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

    return "\n\n---\n\n".join(parts)


def build_cron_prompt() -> str:
    """Build the system prompt for cron executions: standard prompt + Prompt_Cron.md."""
    base = build_system_prompt()
    ws = Path(cfg.workspace_path)
    cron_md = _read_if_exists(ws / "Prompt_Cron.md")
    if cron_md:
        return base + "\n\n---\n\n## Cron Instructions\n" + cron_md
    return base

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.config import cfg  # noqa: E402
from agent.prompt import build_system_prompt, _summarize_skill  # noqa: E402


class PromptTests(unittest.TestCase):
    def test_build_system_prompt_uses_compact_skills_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "skills" / "zeta").mkdir(parents=True)
            (ws / "skills" / "alpha").mkdir(parents=True)
            (ws / "skills" / "alpha" / "SKILL.md").write_text(
                "# Alpha\n\n## Purpose\nAlpha skill summary.\n\n## Instructions\nDetailed alpha instructions."
            )
            (ws / "skills" / "zeta" / "SKILL.md").write_text(
                "# Zeta\n\n## Purpose\nZeta skill summary.\n\n## Workflow\nDetailed zeta workflow."
            )

            old_workspace_path = cfg.workspace_path
            try:
                cfg.workspace_path = str(ws)
                prompt = build_system_prompt()
            finally:
                cfg.workspace_path = old_workspace_path

        self.assertIn("## Skills Index", prompt)
        self.assertIn(
            f"- alpha: Alpha skill summary. Read {ws / 'skills' / 'alpha' / 'SKILL.md'} with read_file if needed.",
            prompt,
        )
        self.assertIn(
            f"- zeta: Zeta skill summary. Read {ws / 'skills' / 'zeta' / 'SKILL.md'} with read_file if needed.",
            prompt,
        )
        self.assertIn("read its SKILL.md with read_file before following it", prompt)
        self.assertNotIn("Detailed alpha instructions.", prompt)
        self.assertNotIn("Detailed zeta workflow.", prompt)
        self.assertLess(prompt.index("- alpha:"), prompt.index("- zeta:"))

    def test_summarize_skill_prefers_purpose(self):
        skill_md = (
            "# Skill\n\n"
            "## Purpose\n"
            "Help the agent do the main task.\n"
            "\n## Use This Skill When\n"
            "- A fallback that should not be used.\n"
        )
        self.assertEqual(_summarize_skill(skill_md), "Help the agent do the main task")

    def test_summarize_skill_falls_back_to_first_use_when_bullet(self):
        skill_md = (
            "# Skill\n\n"
            "## Use This Skill When\n"
            "- The user asks for a reusable workflow.\n"
            "- Another condition.\n"
        )
        self.assertEqual(_summarize_skill(skill_md), "The user asks for a reusable workflow")

    def test_summarize_skill_falls_back_to_first_non_heading_line(self):
        skill_md = (
            "# Skill\n\n"
            "Plain text fallback summary.\n"
            "\n## Details\n"
            "More details.\n"
        )
        self.assertEqual(_summarize_skill(skill_md), "Plain text fallback summary")

    def test_summarize_skill_uses_default_when_empty(self):
        self.assertEqual(_summarize_skill("# Skill\n\n## Empty\n"), "No description available.")

    def test_build_system_prompt_skips_recent_tool_calls_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            old_workspace_path = cfg.workspace_path
            old_include_recent_tool_calls = cfg.include_recent_tool_calls
            old_timezone = cfg.timezone
            try:
                cfg.workspace_path = str(ws)
                cfg.include_recent_tool_calls = False
                cfg.timezone = "UTC"
                with patch(
                    "agent.prompt.get_recent_tool_calls",
                    return_value=[
                        {
                            "tool_name": "ha_get_state",
                            "input_summary": "{'entity_id': 'light.kitchen'}",
                            "success": True,
                            "duration_ms": 12,
                            "timestamp": "2026-04-12T10:00:00+00:00",
                        }
                    ],
                ):
                    prompt = build_system_prompt(chat_id=123)
            finally:
                cfg.workspace_path = old_workspace_path
                cfg.include_recent_tool_calls = old_include_recent_tool_calls
                cfg.timezone = old_timezone

        self.assertNotIn("## Recent Tool Calls", prompt)
        self.assertNotIn("ha_get_state", prompt)

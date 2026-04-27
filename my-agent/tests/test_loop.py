import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.modules.setdefault("openai", SimpleNamespace(AsyncOpenAI=MagicMock()))

from agent.loop import _log_llm_request  # noqa: E402


class LoopLoggingTests(unittest.TestCase):
    def test_log_llm_request_accepts_mixed_message_types(self):
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            SimpleNamespace(role="assistant", content="tool call incoming", tool_calls=[]),
            {"role": "tool", "tool_call_id": "call_123", "content": "tool result"},
        ]

        with patch("agent.loop.logger.isEnabledFor", return_value=True), patch("agent.loop.logger.debug"):
            _log_llm_request(42, "gpt-4.1-mini", messages, tools=[])


if __name__ == "__main__":
    unittest.main()

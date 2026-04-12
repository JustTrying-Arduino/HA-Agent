import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

telegram_stub = SimpleNamespace(Update=object)
telegram_ext_stub = SimpleNamespace(
    Application=MagicMock(),
    MessageHandler=MagicMock(),
    ContextTypes=SimpleNamespace(DEFAULT_TYPE=object),
    filters=SimpleNamespace(TEXT=object(), VOICE=object(), AUDIO=object()),
)

sys.modules.setdefault("openai", SimpleNamespace(AsyncOpenAI=MagicMock()))
sys.modules.setdefault("requests", SimpleNamespace(post=MagicMock()))
sys.modules.setdefault("telegram", telegram_stub)
sys.modules.setdefault("telegram.ext", telegram_ext_stub)

from agent.telegram import _finalize_response  # noqa: E402


class TelegramFinalizeResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalize_response_deletes_placeholder_when_response_is_empty(self):
        update = SimpleNamespace()
        status_message = AsyncMock()

        with patch("agent.telegram._safe_delete_message", new=AsyncMock()) as delete_mock, patch(
            "agent.telegram._safe_edit_message", new=AsyncMock()
        ) as edit_mock, patch("agent.telegram._send_response", new=AsyncMock()) as send_mock:
            await _finalize_response(update, status_message, {"current_text": "En reflexion..."}, "")

        delete_mock.assert_awaited_once_with(status_message)
        edit_mock.assert_not_awaited()
        send_mock.assert_not_awaited()

    async def test_finalize_response_deletes_placeholder_when_response_is_whitespace_only(self):
        update = SimpleNamespace()
        status_message = AsyncMock()

        with patch("agent.telegram._safe_delete_message", new=AsyncMock()) as delete_mock, patch(
            "agent.telegram._safe_edit_message", new=AsyncMock()
        ) as edit_mock, patch("agent.telegram._send_response", new=AsyncMock()) as send_mock:
            await _finalize_response(update, status_message, {"current_text": "En reflexion..."}, "   \n\t")

        delete_mock.assert_awaited_once_with(status_message)
        edit_mock.assert_not_awaited()
        send_mock.assert_not_awaited()

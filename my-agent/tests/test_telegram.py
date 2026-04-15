import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from unittest.mock import MagicMock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

telegram_stub = SimpleNamespace(Update=object)
telegram_constants_stub = SimpleNamespace(ParseMode=SimpleNamespace(HTML="HTML"))
telegram_ext_stub = SimpleNamespace(
    Application=MagicMock(),
    MessageHandler=MagicMock(),
    ContextTypes=SimpleNamespace(DEFAULT_TYPE=object),
    filters=SimpleNamespace(TEXT=object(), VOICE=object(), AUDIO=object()),
)

sys.modules.setdefault("openai", SimpleNamespace(AsyncOpenAI=MagicMock()))
sys.modules.setdefault("requests", SimpleNamespace(post=MagicMock()))
sys.modules.setdefault("telegram", telegram_stub)
sys.modules.setdefault("telegram.constants", telegram_constants_stub)
sys.modules.setdefault("telegram.ext", telegram_ext_stub)

from agent.scheduler import send_text  # noqa: E402
from agent.telegram import _finalize_response, _safe_edit_message, build_telegram_chunks  # noqa: E402


PARSE_MODE_HTML = telegram_constants_stub.ParseMode.HTML


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

    async def test_finalize_response_edits_placeholder_with_html_parse_mode_for_single_chunk(self):
        update = SimpleNamespace()
        status_message = AsyncMock()
        state = {"current_text": "En reflexion...", "current_parse_mode": None}

        await _finalize_response(update, status_message, state, "<b>Resume</b>\n\n<code>ok</code>")

        status_message.edit_text.assert_awaited_once_with(
            "<b>Resume</b>\n\n<code>ok</code>",
            parse_mode=PARSE_MODE_HTML,
        )
        self.assertEqual(state["current_text"], "<b>Resume</b>\n\n<code>ok</code>")
        self.assertEqual(state["current_parse_mode"], PARSE_MODE_HTML)

    async def test_safe_edit_message_retries_as_plain_text_when_html_edit_fails(self):
        message = AsyncMock()
        message.edit_text = AsyncMock(side_effect=[RuntimeError("bad html"), None])
        state = {"current_text": "En reflexion...", "current_parse_mode": None}

        await _safe_edit_message(message, state, "<b>Resume</b>", parse_mode=PARSE_MODE_HTML)

        self.assertEqual(
            message.edit_text.await_args_list,
            [
                call("<b>Resume</b>", parse_mode=PARSE_MODE_HTML),
                call("Resume", parse_mode=None),
            ],
        )
        self.assertEqual(state["current_text"], "Resume")
        self.assertIsNone(state["current_parse_mode"])

    async def test_finalize_response_deletes_placeholder_and_sends_multiple_html_chunks(self):
        long_text = "<b>Titre</b>\n\n" + ("A" * 4090) + "\n\n<i>Fin</i>"
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        status_message = AsyncMock()
        state = {"current_text": "En reflexion...", "current_parse_mode": None}

        await _finalize_response(update, status_message, state, long_text)

        status_message.delete.assert_awaited_once()
        self.assertEqual(update.message.reply_text.await_count, 3)
        for awaited in update.message.reply_text.await_args_list:
            self.assertEqual(awaited.kwargs["parse_mode"], PARSE_MODE_HTML)

    async def test_finalize_response_downgrades_oversized_pre_block_to_plain_text_chunks(self):
        oversized_pre = "<pre>" + ("x" * 5000) + "</pre>"
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        status_message = AsyncMock()
        state = {"current_text": "En reflexion...", "current_parse_mode": None}

        await _finalize_response(update, status_message, state, oversized_pre)

        status_message.delete.assert_awaited_once()
        self.assertEqual(update.message.reply_text.await_count, 2)
        for awaited in update.message.reply_text.await_args_list:
            self.assertIsNone(awaited.kwargs["parse_mode"])
        sent_text = "".join(awaited.args[0] for awaited in update.message.reply_text.await_args_list)
        self.assertEqual(sent_text, "x" * 5000)


class TelegramChunkingTests(unittest.TestCase):
    def test_build_telegram_chunks_keeps_html_for_simple_paragraphs(self):
        chunks = build_telegram_chunks("<b>Resume</b>\n\nTexte")

        self.assertEqual(
            chunks,
            [{"text": "<b>Resume</b>\n\nTexte", "parse_mode": PARSE_MODE_HTML}],
        )

    def test_build_telegram_chunks_only_downgrades_oversized_formatted_block(self):
        text = "<b>Resume</b>\n\n<pre>" + ("x" * 5000) + "</pre>\n\n<i>Fin</i>"

        chunks = build_telegram_chunks(text)

        self.assertEqual(chunks[0], {"text": "<b>Resume</b>", "parse_mode": PARSE_MODE_HTML})
        self.assertIsNone(chunks[1]["parse_mode"])
        self.assertIsNone(chunks[2]["parse_mode"])
        self.assertEqual(chunks[1]["text"] + chunks[2]["text"], "x" * 5000)
        self.assertEqual(chunks[3], {"text": "<i>Fin</i>", "parse_mode": PARSE_MODE_HTML})


class SchedulerTelegramTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_text_uses_html_parse_mode_for_short_message(self):
        bot = AsyncMock()

        await send_text(bot, 123, "<b>Resume</b>")

        bot.send_message.assert_awaited_once_with(
            chat_id=123,
            text="<b>Resume</b>",
            parse_mode=PARSE_MODE_HTML,
        )

    async def test_send_text_retries_as_plain_text_when_html_send_fails(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=[RuntimeError("bad html"), None])

        await send_text(bot, 123, "<b>Resume</b>")

        self.assertEqual(
            bot.send_message.await_args_list,
            [
                call(chat_id=123, text="<b>Resume</b>", parse_mode=PARSE_MODE_HTML),
                call(chat_id=123, text="Resume", parse_mode=None),
            ],
        )

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

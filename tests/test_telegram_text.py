from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.bot.utils.telegram_text import edit_or_send_long_message, send_long_message, split_text_for_telegram
from tests.fakes import FakeMessage


def test_short_text_sent_in_single_message() -> None:
    message = FakeMessage(text="test")
    asyncio.run(send_long_message(message, "короткий текст", limit=50))
    message.answer.assert_awaited_once_with("короткий текст")


def test_split_long_text_preserves_full_content() -> None:
    text = ("строка 1\n" * 40) + "конец"
    chunks = split_text_for_telegram(text, limit=80)
    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(len(chunk) <= 80 for chunk in chunks)


def test_split_prefers_line_boundaries() -> None:
    text = "aa\n\nbb\n\ncc\n\ndd"
    chunks = split_text_for_telegram(text, limit=7)
    assert chunks[0].endswith("\n")
    assert "".join(chunks) == text


def test_edit_text_used_only_when_text_fits_limit() -> None:
    message = FakeMessage(text="test")
    asyncio.run(edit_or_send_long_message(message, "маленький", limit=20))
    message.edit_text.assert_awaited_once_with("маленький")
    message.answer.assert_not_awaited()


def test_long_edit_flow_sends_notice_and_chunks_without_failing() -> None:
    message = FakeMessage(text="test")

    async def guarded_edit(text: str, **kwargs):
        if len(text) > 100:
            raise RuntimeError("message is too long")
        return None

    message.edit_text = AsyncMock(side_effect=guarded_edit)
    long_text = "x" * 250

    asyncio.run(edit_or_send_long_message(message, long_text, limit=100))

    first_edit_text = message.edit_text.await_args_list[0].args[0]
    assert "Отчет слишком большой" in first_edit_text
    assert message.answer.await_count == 3
    delivered = "".join(call.args[0] for call in message.answer.await_args_list)
    assert delivered == long_text

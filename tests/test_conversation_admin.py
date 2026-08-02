from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers.conversation_admin import conversation_close, conversation_users, conversation_view
from tests.fakes import FakeCallback, FakeMessage


def _write_log(path: Path, user_id: int = 100) -> None:
    records = [
        {
            "recorded_at": "2026-08-01T22:00:00+00:00",
            "direction": "incoming",
            "chat_id": user_id,
            "first_name": "Tester",
            "username": "tester",
            "text": "Привет",
        },
        {
            "recorded_at": "2026-08-01T22:00:01+00:00",
            "direction": "outgoing",
            "chat_id": user_id,
            "text": "Здравствуйте",
        },
    ]
    path.mkdir(parents=True, exist_ok=True)
    (path / f"user_{user_id}.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_admin_can_open_user_list_and_view_history(app_context, tmp_path: Path):
    _write_log(tmp_path)
    app_context.settings.conversation_log_enabled = True
    app_context.settings.conversation_log_dir = str(tmp_path)

    message = FakeMessage(text="💬 Переписки с ботом", user_id=1)
    await conversation_users(message, app_context)

    markup = message.answer.await_args.kwargs["reply_markup"]
    assert "Переписки с ботом" in message.answer.await_args.args[0]
    assert markup.inline_keyboard[0][0].callback_data == "conversation:view:100:0"

    callback = FakeCallback(data="conversation:view:100:0", user_id=1)
    await conversation_view(callback, app_context)

    text = callback.message.edit_text.await_args.args[0]
    assert "Tester" in text
    assert "Привет" in text
    assert "Здравствуйте" in text
    history_markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    assert history_markup.inline_keyboard[-1][0].callback_data == "conversation:close"


@pytest.mark.asyncio
async def test_non_admin_cannot_view_conversations(app_context, tmp_path: Path):
    _write_log(tmp_path)
    app_context.settings.conversation_log_enabled = True
    app_context.settings.conversation_log_dir = str(tmp_path)

    message = FakeMessage(text="💬 Переписки с ботом", user_id=999)
    await conversation_users(message, app_context)

    assert "Недостаточно прав" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_close_button_deletes_history_message(app_context):
    callback = FakeCallback(data="conversation:close", user_id=1)
    callback.message.delete = AsyncMock()

    await conversation_close(callback, app_context)

    callback.message.delete.assert_awaited_once()
    callback.answer.assert_awaited_once()

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bot.states.registration import RegistrationStates
from app.conversations.logger import ConversationLogger, incoming_record, outgoing_record
from app.conversations.middlewares import (
    IncomingConversationMiddleware,
    OutgoingConversationMiddleware,
    suppress_outgoing_conversation_logging,
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def private_message(text: str, *, user_id: int = 101, message_id: int = 7):
    user = SimpleNamespace(id=user_id, username="tester", first_name="Test", last_name="User")
    chat = SimpleNamespace(id=user_id, type="private")
    return SimpleNamespace(
        chat=chat,
        from_user=user,
        text=text,
        caption=None,
        content_type="text",
        message_id=message_id,
        reply_to_message=None,
        photo=None,
        document=None,
        audio=None,
        video=None,
        animation=None,
        voice=None,
        video_note=None,
        sticker=None,
        contact=None,
        location=None,
    )


def test_conversation_logger_separates_private_users(tmp_path):
    conversation_logger = ConversationLogger(tmp_path)
    first = conversation_logger.write(direction="incoming", chat_id=101, chat_type="private", text="one")
    second = conversation_logger.write(direction="incoming", chat_id=202, chat_type="private", text="two")

    assert first.name == "user_101.jsonl"
    assert second.name == "user_202.jsonl"
    assert read_jsonl(first)[0]["text"] == "one"
    assert read_jsonl(second)[0]["text"] == "two"
    assert oct(first.stat().st_mode & 0o777) == "0o600"


def test_conversation_logger_rotates_each_user_independently(tmp_path):
    conversation_logger = ConversationLogger(tmp_path, max_bytes=250, backup_count=2)
    for index in range(8):
        conversation_logger.write(
            direction="incoming",
            chat_id=101,
            chat_type="private",
            text=f"{index}-" + "x" * 100,
        )

    assert (tmp_path / "user_101.jsonl").exists()
    assert (tmp_path / "user_101.jsonl.1").exists()
    assert not (tmp_path / "user_202.jsonl").exists()


def test_incoming_record_redacts_player_token():
    message = private_message("SECRET-PLAYER-TOKEN")
    update = SimpleNamespace(update_id=99, event_type="message", event=message)

    record = incoming_record(update, {"raw_state": RegistrationStates.waiting_for_player_token.state})

    assert record is not None
    _chat_id, _chat_type, fields = record
    assert fields["text"] == "[REDACTED: player token]"
    assert fields["secret_redacted"] is True
    assert "SECRET-PLAYER-TOKEN" not in json.dumps(fields)


@pytest.mark.asyncio
async def test_incoming_middleware_does_not_break_handler_when_log_write_fails():
    class BrokenLogger:
        def write(self, **_kwargs):
            raise OSError("disk unavailable")

    update = SimpleNamespace(update_id=99, event_type="message", event=private_message("hello"))
    middleware = IncomingConversationMiddleware(BrokenLogger())
    called = False

    async def handler(_event, _data):
        nonlocal called
        called = True
        return "ok"

    assert await middleware(handler, update, {}) == "ok"
    assert called is True


class SendMessage:
    def __init__(self, chat_id: int, text: str):
        self.chat_id = chat_id
        self.text = text
        self.caption = None
        self.message_id = None
        self.media = None
        self.from_chat_id = None


class GetMe:
    pass


def test_outgoing_record_logs_successful_messages_only():
    method = SendMessage(101, "bot reply")
    result = SimpleNamespace(
        chat=SimpleNamespace(id=101, type="private", username="tester", first_name="Test", last_name="User"),
        message_id=8,
        text="bot reply",
        caption=None,
    )

    record = outgoing_record(method, result)

    assert record is not None
    chat_id, chat_type, fields = record
    assert chat_id == 101 and chat_type == "private"
    assert fields["bot_method"] == "SendMessage"
    assert fields["text"] == "bot reply"
    assert outgoing_record(GetMe(), SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_outgoing_middleware_writes_after_success(tmp_path):
    conversation_logger = ConversationLogger(tmp_path)
    middleware = OutgoingConversationMiddleware(conversation_logger)
    method = SendMessage(101, "bot reply")
    result = SimpleNamespace(
        chat=SimpleNamespace(id=101, type="private", username="tester", first_name="Test", last_name="User"),
        message_id=8,
        text="bot reply",
        caption=None,
    )

    async def make_request(_bot, _method):
        return result

    returned = await middleware(make_request, SimpleNamespace(), method)

    assert returned is result
    rows = read_jsonl(tmp_path / "user_101.jsonl")
    assert rows[0]["direction"] == "outgoing"
    assert rows[0]["text"] == "bot reply"


@pytest.mark.asyncio
async def test_outgoing_middleware_skips_suppressed_admin_history(tmp_path):
    conversation_logger = ConversationLogger(tmp_path)
    middleware = OutgoingConversationMiddleware(conversation_logger)
    method = SendMessage(1, "чужая переписка")
    result = SimpleNamespace(
        chat=SimpleNamespace(id=1, type="private", username="admin", first_name="Admin", last_name=None),
        message_id=9,
        text="чужая переписка",
        caption=None,
    )

    async def make_request(_bot, _method):
        return result

    with suppress_outgoing_conversation_logging():
        returned = await middleware(make_request, SimpleNamespace(), method)

    assert returned is result
    assert not (tmp_path / "user_1.jsonl").exists()

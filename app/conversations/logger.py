from __future__ import annotations

import fcntl
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_PRIVATE_CHAT_TYPE = "private"
_SECRET_REDACTION = "[REDACTED: player token]"
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def safe_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def snake_case(name: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", name).lower()


class ConversationLogger:
    """Append-only, per-chat JSONL conversation storage with file rotation."""

    def __init__(
        self,
        directory: str | Path,
        *,
        max_bytes: int = 5_000_000,
        backup_count: int = 3,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if backup_count < 0:
            raise ValueError("backup_count must be non-negative")
        self.directory = Path(directory)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)

    def _path_for(self, chat_id: int, chat_type: str | None) -> Path:
        normalized_type = str(enum_value(chat_type)) if chat_type is not None else None
        if normalized_type == _PRIVATE_CHAT_TYPE or (normalized_type is None and chat_id > 0):
            return self.directory / f"user_{chat_id}.jsonl"
        return self.directory / f"chat_{abs(chat_id)}.jsonl"

    def _rotate_locked(self, path: Path, incoming_bytes: int) -> None:
        try:
            current_size = path.stat().st_size
        except FileNotFoundError:
            return
        if current_size + incoming_bytes <= self.max_bytes:
            return
        if self.backup_count == 0:
            path.unlink(missing_ok=True)
            return
        oldest = path.with_name(f"{path.name}.{self.backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            target = path.with_name(f"{path.name}.{index + 1}")
            if source.exists():
                os.replace(source, target)
        os.replace(path, path.with_name(f"{path.name}.1"))

    def write(
        self,
        *,
        direction: str,
        chat_id: int,
        chat_type: str | None = None,
        **fields: Any,
    ) -> Path:
        if direction not in {"incoming", "outgoing"}:
            raise ValueError("direction must be incoming or outgoing")
        if not isinstance(chat_id, int):
            raise TypeError("chat_id must be int")

        path = self._path_for(chat_id, chat_type)
        record = {
            "schema_version": _SCHEMA_VERSION,
            "recorded_at": utc_now(),
            "direction": direction,
            "chat_id": chat_id,
            "chat_type": str(enum_value(chat_type)) if chat_type is not None else None,
            **fields,
        }
        payload = (json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8")
        lock_path = path.with_name(f".{path.name}.lock")
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)

        with lock_path.open("a+b") as lock_stream:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            self._rotate_locked(path, len(payload))
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                with os.fdopen(fd, "ab", closefd=True) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        return path


def redact_incoming_text(text: str | None, raw_state: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    if raw_state and raw_state.endswith(":waiting_for_player_token"):
        return _SECRET_REDACTION, True
    return text, False


def _message_media_metadata(message: Any) -> dict[str, Any] | None:
    photo = getattr(message, "photo", None)
    if photo:
        item = photo[-1]
        return {
            "kind": "photo",
            "file_unique_id": getattr(item, "file_unique_id", None),
            "file_size": getattr(item, "file_size", None),
            "width": getattr(item, "width", None),
            "height": getattr(item, "height", None),
        }

    for attribute in ("document", "audio", "video", "animation", "voice", "video_note", "sticker"):
        item = getattr(message, attribute, None)
        if item is None:
            continue
        return {
            "kind": attribute,
            "file_unique_id": getattr(item, "file_unique_id", None),
            "file_name": getattr(item, "file_name", None),
            "mime_type": getattr(item, "mime_type", None),
            "file_size": getattr(item, "file_size", None),
            "duration": getattr(item, "duration", None),
            "width": getattr(item, "width", None),
            "height": getattr(item, "height", None),
        }
    return None


def incoming_record(event: Any, data: dict[str, Any]) -> tuple[int, str | None, dict[str, Any]] | None:
    event_type = str(enum_value(getattr(event, "event_type", "unknown")))
    inner = getattr(event, "event", None)
    if inner is None:
        return None

    if event_type == "callback_query":
        message = getattr(inner, "message", None)
        chat = getattr(message, "chat", None)
        user = getattr(inner, "from_user", None)
        chat_id = getattr(chat, "id", None)
        if not isinstance(chat_id, int):
            return None
        return chat_id, enum_value(getattr(chat, "type", None)), {
            "update_id": getattr(event, "update_id", None),
            "update_type": event_type,
            "user_id": getattr(user, "id", None),
            "username": getattr(user, "username", None),
            "first_name": getattr(user, "first_name", None),
            "last_name": getattr(user, "last_name", None),
            "message_id": getattr(message, "message_id", None),
            "content_type": "callback_query",
            "text": safe_text(getattr(inner, "data", None)),
            "fsm_state": data.get("raw_state"),
        }

    chat = getattr(inner, "chat", None)
    user = getattr(inner, "from_user", None)
    chat_id = getattr(chat, "id", None)
    if not isinstance(chat_id, int):
        return None
    original_text = safe_text(getattr(inner, "text", None)) or safe_text(getattr(inner, "caption", None))
    text, redacted = redact_incoming_text(original_text, data.get("raw_state"))
    content_type = str(enum_value(getattr(inner, "content_type", event_type)))
    contact = getattr(inner, "contact", None)
    location = getattr(inner, "location", None)
    return chat_id, enum_value(getattr(chat, "type", None)), {
        "update_id": getattr(event, "update_id", None),
        "update_type": event_type,
        "user_id": getattr(user, "id", None),
        "username": getattr(user, "username", None),
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "message_id": getattr(inner, "message_id", None),
        "reply_to_message_id": getattr(getattr(inner, "reply_to_message", None), "message_id", None),
        "content_type": content_type,
        "text": text,
        "secret_redacted": redacted,
        "fsm_state": data.get("raw_state"),
        "media": _message_media_metadata(inner),
        "contact": (
            {
                "phone_number": getattr(contact, "phone_number", None),
                "first_name": getattr(contact, "first_name", None),
                "last_name": getattr(contact, "last_name", None),
                "user_id": getattr(contact, "user_id", None),
            }
            if contact is not None
            else None
        ),
        "location": (
            {
                "latitude": getattr(location, "latitude", None),
                "longitude": getattr(location, "longitude", None),
            }
            if location is not None
            else None
        ),
    }


def _outgoing_text(method: Any, result: Any) -> str | None:
    for source in (result, method):
        text = safe_text(getattr(source, "text", None)) or safe_text(getattr(source, "caption", None))
        if text is not None:
            return text
    return None


def outgoing_record(method: Any, result: Any) -> tuple[int, str | None, dict[str, Any]] | None:
    method_name = type(method).__name__
    allowed = {
        "SendMessage",
        "SendPhoto",
        "SendAudio",
        "SendDocument",
        "SendVideo",
        "SendAnimation",
        "SendVoice",
        "SendVideoNote",
        "SendSticker",
        "SendMediaGroup",
        "SendLocation",
        "SendVenue",
        "SendContact",
        "SendPoll",
        "SendDice",
        "CopyMessage",
        "ForwardMessage",
        "EditMessageText",
        "EditMessageCaption",
        "EditMessageMedia",
        "DeleteMessage",
        "DeleteMessages",
    }
    if method_name not in allowed:
        return None

    result_chat = getattr(result, "chat", None)
    chat_id = getattr(result_chat, "id", None)
    if not isinstance(chat_id, int):
        chat_id = getattr(method, "chat_id", None)
    if not isinstance(chat_id, int):
        return None

    media_items = getattr(method, "media", None)
    media_count = len(media_items) if isinstance(media_items, (list, tuple)) else None
    media_captions = None
    if media_count is not None:
        media_captions = [safe_text(getattr(item, "caption", None)) for item in media_items]

    content_type = snake_case(method_name.removeprefix("Send").removeprefix("EditMessage")) or "message"
    return chat_id, enum_value(getattr(result_chat, "type", None)), {
        "bot_method": method_name,
        "message_id": getattr(result, "message_id", None) or getattr(method, "message_id", None),
        "content_type": content_type,
        "text": _outgoing_text(method, result),
        "chat_username": getattr(result_chat, "username", None),
        "chat_first_name": getattr(result_chat, "first_name", None),
        "chat_last_name": getattr(result_chat, "last_name", None),
        "media_count": media_count,
        "media_captions": media_captions,
        "source_chat_id": getattr(method, "from_chat_id", None),
        "source_message_id": getattr(method, "message_id", None) if method_name in {"CopyMessage", "ForwardMessage"} else None,
    }

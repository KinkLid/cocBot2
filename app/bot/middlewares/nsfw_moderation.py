from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message

from app.services.nsfw_moderation import NsfwModerationService, NsfwQueueItem

logger = logging.getLogger(__name__)


class NsfwModerationMiddleware(BaseMiddleware):
    def __init__(self, service: NsfwModerationService) -> None:
        self.service = service

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if (
            not self.service.enabled
            or event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}
            or not self.service.is_target_chat(event.chat.id)
        ):
            return await handler(event, data)

        author = event.from_user
        if author is None or author.is_bot:
            return await handler(event, data)

        media = _extract_media(event)
        if media is None:
            return await handler(event, data)

        file_id, media_kind = media
        queued = self.service.enqueue(
            NsfwQueueItem(
                chat_id=event.chat.id,
                message_id=event.message_id,
                telegram_user_id=author.id,
                username=author.username,
                display_name=author.full_name,
                file_id=file_id,
                media_kind=media_kind,
            )
        )
        if not queued:
            logger.warning(
                "NSFW media was not queued: chat_id=%s message_id=%s kind=%s",
                event.chat.id,
                event.message_id,
                media_kind,
            )
        return await handler(event, data)


def _extract_media(message: Message) -> tuple[str, str] | None:
    if message.photo:
        return message.photo[-1].file_id, "image"
    if message.video is not None:
        return message.video.file_id, "video"
    if message.animation is not None:
        return message.animation.file_id, "video"
    if message.video_note is not None:
        return message.video_note.file_id, "video"
    if message.document is not None:
        mime_type = (message.document.mime_type or "").lower()
        if mime_type.startswith("image/"):
            return message.document.file_id, "image"
        if mime_type.startswith("video/"):
            return message.document.file_id, "video"
    if message.sticker is not None:
        if message.sticker.is_animated:
            logger.info(
                "Animated TGS sticker skipped by NSFW moderation: chat_id=%s message_id=%s",
                message.chat.id,
                message.message_id,
            )
            return None
        if message.sticker.is_video:
            return message.sticker.file_id, "video"
        return message.sticker.file_id, "image"
    return None

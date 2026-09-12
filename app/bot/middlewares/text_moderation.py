from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import TextModerationConfig
from app.services.chat_moderation_mutes import ChatModerationMuteService
from app.services.text_moderation import TextModerationDetector

logger = logging.getLogger(__name__)


class TextModerationMiddleware(BaseMiddleware):
    def __init__(
        self,
        config: TextModerationConfig,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        self.config = config
        self.session_maker = session_maker
        self.detector = TextModerationDetector(config)
        self._chat_ids = set(config.chat_ids)

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not self.config.enabled:
            return await handler(event, data)
        if event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return await handler(event, data)
        if event.chat.id not in self._chat_ids:
            return await handler(event, data)

        author = event.from_user
        if author is None or author.is_bot:
            return await handler(event, data)

        match = self.detector.detect(event.text or event.caption)
        if match is None:
            return await handler(event, data)

        bot = data.get("bot")
        if not isinstance(bot, Bot):
            logger.error(
                "Text moderation matched but Bot instance is unavailable: chat_id=%s message_id=%s rule=%s",
                event.chat.id,
                event.message_id,
                match.rule_id,
            )
            return None

        deleted = False
        muted = False
        author_is_admin = False

        try:
            await bot.delete_message(chat_id=event.chat.id, message_id=event.message_id)
            deleted = True
        except TelegramAPIError as exc:
            logger.warning(
                "Unable to delete moderated message: chat_id=%s message_id=%s user_id=%s rule=%s error=%s",
                event.chat.id,
                event.message_id,
                author.id,
                match.rule_id,
                type(exc).__name__,
            )

        try:
            member = await bot.get_chat_member(chat_id=event.chat.id, user_id=author.id)
            author_is_admin = member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}
            if not author_is_admin and event.chat.type == ChatType.SUPERGROUP:
                muted_at = datetime.now(UTC)
                muted_until = muted_at + timedelta(minutes=self.config.mute_minutes)
                await bot.restrict_chat_member(
                    chat_id=event.chat.id,
                    user_id=author.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=muted_until,
                )
                muted = True
                try:
                    async with self.session_maker() as session:
                        await ChatModerationMuteService(session).record_mute(
                            chat_id=event.chat.id,
                            telegram_user_id=author.id,
                            username=author.username,
                            display_name=author.full_name,
                            rule_id=match.rule_id,
                            muted_at=muted_at,
                            muted_until=muted_until,
                        )
                        await session.commit()
                except Exception:
                    logger.exception(
                        "Unable to persist moderation mute: chat_id=%s user_id=%s rule=%s",
                        event.chat.id,
                        author.id,
                        match.rule_id,
                    )
        except TelegramAPIError as exc:
            logger.warning(
                "Unable to restrict moderated user: chat_id=%s user_id=%s rule=%s error=%s",
                event.chat.id,
                author.id,
                match.rule_id,
                type(exc).__name__,
            )

        logger.warning(
            "Text moderation action: chat_id=%s message_id=%s user_id=%s rule=%s deleted=%s muted=%s admin=%s",
            event.chat.id,
            event.message_id,
            author.id,
            match.rule_id,
            deleted,
            muted,
            author_is_admin,
        )

        # A matched abusive message must not continue into command/business handlers,
        # even when Telegram temporarily rejects delete/restrict operations.
        return None

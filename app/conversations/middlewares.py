from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware

from app.conversations.logger import ConversationLogger, incoming_record, outgoing_record

logger = logging.getLogger(__name__)


class IncomingConversationMiddleware(BaseMiddleware):
    def __init__(self, conversation_logger: ConversationLogger) -> None:
        self.conversation_logger = conversation_logger

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        try:
            record = incoming_record(event, data)
            if record is not None:
                chat_id, chat_type, fields = record
                self.conversation_logger.write(
                    direction="incoming",
                    chat_id=chat_id,
                    chat_type=chat_type,
                    **fields,
                )
        except Exception:
            logger.exception("Unable to write incoming conversation log")
        return await handler(event, data)


class OutgoingConversationMiddleware(BaseRequestMiddleware):
    def __init__(self, conversation_logger: ConversationLogger) -> None:
        self.conversation_logger = conversation_logger

    async def __call__(
        self,
        make_request: Callable[[Bot, Any], Awaitable[Any]],
        bot: Bot,
        method: Any,
    ) -> Any:
        result = await make_request(bot, method)
        try:
            record = outgoing_record(method, result)
            if record is not None:
                chat_id, chat_type, fields = record
                self.conversation_logger.write(
                    direction="outgoing",
                    chat_id=chat_id,
                    chat_type=chat_type,
                    **fields,
                )
        except Exception:
            logger.exception("Unable to write outgoing conversation log")
        return result

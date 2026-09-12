from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import admin, admin_panel, common, conversation_admin, moderation_admin, registration, start, stats
from app.bot.middlewares.context import ContextMiddleware
from app.bot.middlewares.nsfw_moderation import NsfwModerationMiddleware
from app.bot.middlewares.text_moderation import TextModerationMiddleware
from app.bot.middlewares.update_audit import UpdateAuditMiddleware
from app.container import AppContext
from app.conversations import ConversationLogger, IncomingConversationMiddleware
from app.security.audit import JsonlAudit, SecurityState


def create_dispatcher(
    app_context: AppContext,
    update_audit: JsonlAudit | None = None,
    security_state: SecurityState | None = None,
    conversation_logger: ConversationLogger | None = None,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    if conversation_logger is not None:
        dp.update.outer_middleware(IncomingConversationMiddleware(conversation_logger))
    if update_audit is not None and security_state is not None:
        dp.update.outer_middleware(UpdateAuditMiddleware(update_audit, security_state))
    dp.update.middleware(ContextMiddleware(app_context))
    dp.message.outer_middleware(
        TextModerationMiddleware(app_context.config.text_moderation, app_context.session_maker)
    )
    if app_context.nsfw_moderator is not None:
        dp.message.outer_middleware(NsfwModerationMiddleware(app_context.nsfw_moderator))
    dp.include_router(start.router)
    dp.include_router(common.router)
    dp.include_router(registration.router)
    dp.include_router(stats.router)
    dp.include_router(admin_panel.router)
    dp.include_router(moderation_admin.router)
    dp.include_router(conversation_admin.router)
    dp.include_router(admin.router)
    return dp

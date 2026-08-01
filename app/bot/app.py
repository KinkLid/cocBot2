from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import admin, common, registration, start, stats
from app.bot.middlewares.context import ContextMiddleware
from app.bot.middlewares.update_audit import UpdateAuditMiddleware
from app.container import AppContext
from app.security.audit import JsonlAudit, SecurityState


def create_dispatcher(app_context: AppContext, update_audit: JsonlAudit | None = None, security_state: SecurityState | None = None) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    if update_audit is not None and security_state is not None:
        dp.update.outer_middleware(UpdateAuditMiddleware(update_audit, security_state))
    dp.update.middleware(ContextMiddleware(app_context))
    dp.include_router(start.router)
    dp.include_router(common.router)
    dp.include_router(registration.router)
    dp.include_router(stats.router)
    dp.include_router(admin.router)
    return dp

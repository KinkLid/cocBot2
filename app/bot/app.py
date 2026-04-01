from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import admin, common, registration, start, stats
from app.bot.middlewares.context import ContextMiddleware
from app.container import AppContext


def create_dispatcher(app_context: AppContext) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(ContextMiddleware(app_context))
    dp.include_router(start.router)
    dp.include_router(common.router)
    dp.include_router(registration.router)
    dp.include_router(stats.router)
    dp.include_router(admin.router)
    return dp

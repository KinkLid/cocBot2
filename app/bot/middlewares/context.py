from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware

from app.container import AppContext


class ContextMiddleware(BaseMiddleware):
    def __init__(self, app_context: AppContext) -> None:
        self.app_context = app_context

    async def __call__(self, handler: Callable[[Any, dict[str, Any]], Awaitable[Any]], event: Any, data: dict[str, Any]) -> Any:
        data["app_context"] = self.app_context
        return await handler(event, data)

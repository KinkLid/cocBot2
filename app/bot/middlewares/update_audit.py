from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED

from app.security.audit import JsonlAudit, SecurityState, utc_now


class UpdateAuditMiddleware(BaseMiddleware):
    """Record routing metadata only; never serialize update contents."""

    def __init__(self, audit: JsonlAudit, state: SecurityState) -> None:
        self.audit = audit
        self.state = state

    @staticmethod
    def _handler_name(data: dict[str, Any]) -> str | None:
        handler = data.get("handler")
        callback = getattr(handler, "callback", None)
        if callback is None:
            return None
        return getattr(callback, "__qualname__", getattr(callback, "__name__", None))

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        started = time.monotonic()
        received_at = utc_now()
        update_id = getattr(event, "update_id", None)
        event_type = getattr(event, "event_type", "unknown")
        inner = getattr(event, "event", None)
        chat = getattr(inner, "chat", None)
        user = getattr(inner, "from_user", None)
        fields = {
            "update_id": update_id,
            "received_at": received_at,
            "update_type": str(event_type),
            "chat_id": getattr(chat, "id", None),
            "user_id": getattr(user, "id", None),
            "handler_name": self._handler_name(data),
        }
        handled = False
        success = False
        if isinstance(update_id, int):
            self.state.record_received_update(update_id, received_at=received_at)
        try:
            result = await handler(event, data)
            handled = result is not UNHANDLED
            success = True
            self.audit.write(
                "telegram_update_processed",
                result="handled" if handled else "not_handled",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                **fields,
            )
            return result
        except Exception as exc:
            self.audit.write(
                "telegram_update_processed",
                severity="ERROR",
                result="failure",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                error_class=type(exc).__name__,
                **fields,
            )
            raise
        finally:
            if isinstance(update_id, int):
                self.state.record_completed_update(
                    update_id,
                    completed_at=utc_now(),
                    handled=handled,
                    success=success,
                )

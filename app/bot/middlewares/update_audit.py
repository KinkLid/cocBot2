from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware

from app.security.audit import JsonlAudit, SecurityState, utc_now


class UpdateAuditMiddleware(BaseMiddleware):
    """Records routing metadata only; update contents and callback payloads are never serialized."""

    def __init__(self, audit: JsonlAudit, state: SecurityState) -> None:
        self.audit, self.state = audit, state

    async def __call__(self, handler: Callable[[Any, dict[str, Any]], Awaitable[Any]], event: Any, data: dict[str, Any]) -> Any:
        started = time.monotonic()
        update_id = getattr(event, "update_id", None)
        event_type = getattr(event, "event_type", "unknown")
        inner = getattr(event, "event", None)
        chat = getattr(inner, "chat", None)
        user = getattr(inner, "from_user", None)
        fields = {"update_id": update_id, "received_at": utc_now(), "update_type": str(event_type), "chat_id": getattr(chat, "id", None), "user_id": getattr(user, "id", None)}
        try:
            result = await handler(event, data)
            self.audit.write("telegram_update_processed", result="success", duration_ms=round((time.monotonic() - started) * 1000, 2), **fields)
            return result
        except Exception as exc:
            self.audit.write("telegram_update_processed", severity="ERROR", result="failure", duration_ms=round((time.monotonic() - started) * 1000, 2), error_class=type(exc).__name__, **fields)
            raise
        finally:
            if update_id is not None:
                existing = self.state.read()
                values = {"last_processed_update_id": update_id, "last_processed_update_timestamp": utc_now()}
                if existing.get("webhook_removed_at") and not existing.get("first_recovered_update_after_incident"):
                    values["first_recovered_update_after_incident"] = {"update_id": update_id, "received_at": utc_now()}
                self.state.update(**values)

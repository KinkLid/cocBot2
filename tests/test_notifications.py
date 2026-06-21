from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AdminNotificationHistory
from app.services.notifications import AdminNotifier


@pytest.mark.asyncio
async def test_admin_notifier_continues_after_single_admin_send_failure(session, app_yaml_config):
    calls: list[tuple[int, str]] = []

    async def sender(admin_id: int, text: str) -> None:
        calls.append((admin_id, text))
        if admin_id == 1:
            raise RuntimeError("Telegram send failed")

    notifier = AdminNotifier(session, app_yaml_config, sender)
    now = datetime(2026, 4, 1, tzinfo=UTC)

    await notifier.notify_once(event_key="return:#P1:2026-04-01", event_type="return", text="hello", now=now)
    await session.commit()

    rows = list((await session.execute(select(AdminNotificationHistory).order_by(AdminNotificationHistory.admin_telegram_id))).scalars())
    assert [row.admin_telegram_id for row in rows] == [2]
    assert calls == [(1, "hello"), (2, "hello")]

    await notifier.notify_once(event_key="return:#P1:2026-04-01", event_type="return", text="hello", now=now)
    await session.commit()

    assert calls == [(1, "hello"), (2, "hello"), (1, "hello")]
    rows = list((await session.execute(select(AdminNotificationHistory).order_by(AdminNotificationHistory.admin_telegram_id))).scalars())
    assert [row.admin_telegram_id for row in rows] == [2]

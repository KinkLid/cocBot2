from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers.admin import capital_raid_report_start, dev_capital
from app.services.period import PeriodService
from tests.fakes import FakeMessage


CAPITAL_NO_DATA_TEXT = "⚠️ По столице за текущий цикл пока нет данных."


@pytest.mark.asyncio
async def test_capital_button_reads_current_cycle_without_fsm_or_api(app_context, monkeypatch):
    monkeypatch.setattr(
        PeriodService,
        "current_cycle",
        AsyncMock(return_value=SimpleNamespace(
            start=datetime(2026, 5, 21, tzinfo=UTC), end=datetime(2026, 6, 21, tzinfo=UTC)
        )),
    )
    message = FakeMessage(text="🏰 Столица", user_id=1)
    await capital_raid_report_start(message, app_context)
    assert message.answer.await_args.args[0] == CAPITAL_NO_DATA_TEXT


@pytest.mark.asyncio
async def test_dev_capital_button_reads_current_cycle_without_live_sync(app_context, monkeypatch):
    monkeypatch.setattr(
        PeriodService,
        "current_cycle",
        AsyncMock(return_value=SimpleNamespace(
            start=datetime(2026, 5, 21, tzinfo=UTC), end=datetime(2026, 6, 21, tzinfo=UTC)
        )),
    )
    message = FakeMessage(text="🧪 Dev вклад в столицу", user_id=1)
    await dev_capital(message, app_context)
    assert message.answer.await_args.args[0] == CAPITAL_NO_DATA_TEXT


@pytest.mark.asyncio
async def test_capital_buttons_deny_non_admin(app_context):
    capital = FakeMessage(text="🏰 Столица", user_id=999)
    dev = FakeMessage(text="🧪 Dev вклад в столицу", user_id=999)
    await capital_raid_report_start(capital, app_context)
    await dev_capital(dev, app_context)
    assert "⛔ Недостаточно прав" in capital.answer.await_args.args[0]
    assert "⛔ Недостаточно прав" in dev.answer.await_args.args[0]

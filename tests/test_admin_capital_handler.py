from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.bot.handlers.admin import capital_raid_report_finish, capital_raid_report_start
from app.bot.states.capital import CapitalRaidStates
from tests.fakes import FakeMessage, FakeState


@pytest.mark.asyncio
async def test_capital_button_admin_prompts_for_count(app_context):
    state = FakeState()
    message = FakeMessage(text="🏰 Столица", user_id=1)
    await capital_raid_report_start(message, state, app_context)
    assert state.state == str(CapitalRaidStates.awaiting_capital_raid_count)
    assert "Введите, за сколько последних рейдов" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_capital_button_denies_non_admin(app_context):
    state = FakeState()
    message = FakeMessage(text="🏰 Столица", user_id=999)
    await capital_raid_report_start(message, state, app_context)
    assert "⛔ Недостаточно прав" in message.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_input", "expected"),
    [
        ("abc", "⚠️ Введите целое число от 1 до 10."),
        ("1.5", "⚠️ Введите целое число от 1 до 10."),
        ("0", "⚠️ Число должно быть от 1 до 10."),
        ("-4", "⚠️ Число должно быть от 1 до 10."),
        ("11", "⚠️ Максимум можно запросить 10 последних рейдов."),
    ],
)
async def test_capital_count_validation_errors(app_context, user_input, expected):
    state = FakeState()
    await state.set_state(CapitalRaidStates.awaiting_capital_raid_count)
    message = FakeMessage(text=user_input, user_id=1)
    await capital_raid_report_finish(message, state, app_context)
    assert expected == message.answer.await_args.args[0]
    assert state.state == str(CapitalRaidStates.awaiting_capital_raid_count)


@pytest.mark.asyncio
async def test_capital_count_valid_returns_report_and_clears_state(app_context, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.admin.CapitalRaidReportService.build_recent_weekends_report",
        AsyncMock(return_value="🏰 aggregated"),
    )
    state = FakeState()
    await state.set_state(CapitalRaidStates.awaiting_capital_raid_count)
    message = FakeMessage(text="3", user_id=1)
    await capital_raid_report_finish(message, state, app_context)
    assert message.answer.await_args_list[0].args[0] == "🏰 aggregated"
    assert state.state is None


@pytest.mark.asyncio
async def test_capital_count_back_clears_state_and_returns_menu(app_context):
    state = FakeState()
    await state.set_state(CapitalRaidStates.awaiting_capital_raid_count)
    message = FakeMessage(text="⬅️ Назад", user_id=1)
    await capital_raid_report_finish(message, state, app_context)
    assert state.state is None
    assert message.answer.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_capital_count_exception_returns_safe_message_and_clears_state(app_context, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.admin.CapitalRaidReportService.build_recent_weekends_report",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    state = FakeState()
    await state.set_state(CapitalRaidStates.awaiting_capital_raid_count)
    message = FakeMessage(text="2", user_id=1)
    await capital_raid_report_finish(message, state, app_context)
    assert "⚠️ Не удалось построить отчет по клановой столице" in message.answer.await_args.args[0]
    assert state.state is None

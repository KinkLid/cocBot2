from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers.admin import (
    violation_recalculation_cancel,
    violation_recalculation_confirm,
    violation_recalculation_start,
)
from app.services.violation_recalculation import ViolationRecalculationResult
from tests.fakes import FakeCallback, FakeMessage


class SessionStub:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


def context_with_session(app_context, session):
    @asynccontextmanager
    async def session_maker():
        yield session

    return SimpleNamespace(
        auth_service=app_context.auth_service,
        session_maker=session_maker,
    )


@pytest.mark.asyncio
async def test_non_admin_cannot_start_recalculation(app_context):
    message = FakeMessage("🔄 Пересчитать нарушения текущего цикла", user_id=999)

    await violation_recalculation_start(message, app_context)

    message.answer.assert_awaited_once_with("⛔ Недостаточно прав")


@pytest.mark.asyncio
async def test_non_admin_cannot_call_recalculation_callback(app_context):
    callback = FakeCallback("violation_recalculation:confirm", user_id=999)

    await violation_recalculation_confirm(callback, app_context)

    callback.answer.assert_awaited_once_with("Недостаточно прав", show_alert=True)


@pytest.mark.asyncio
async def test_cancel_does_not_open_database_session(app_context):
    app_context.session_maker = AsyncMock(side_effect=AssertionError("database accessed"))
    callback = FakeCallback("violation_recalculation:cancel", user_id=1)

    await violation_recalculation_cancel(callback, app_context)

    app_context.session_maker.assert_not_called()


@pytest.mark.asyncio
async def test_successful_callback_commits_once(app_context, monkeypatch):
    session = SessionStub()
    context = context_with_session(app_context, session)
    recalculate = AsyncMock(return_value=ViolationRecalculationResult())
    monkeypatch.setattr(
        "app.bot.handlers.admin.ViolationRecalculationService.recalculate_current_cycle",
        recalculate,
    )

    await violation_recalculation_confirm(FakeCallback("violation_recalculation:confirm", 1), context)

    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_error_before_commit_rolls_back(app_context, monkeypatch):
    session = SessionStub()
    context = context_with_session(app_context, session)
    monkeypatch.setattr(
        "app.bot.handlers.admin.ViolationRecalculationService.recalculate_current_cycle",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    callback = FakeCallback("violation_recalculation:confirm", 1)

    await violation_recalculation_confirm(callback, context)

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    assert "Изменения отменены" in callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_result_send_error_after_commit_does_not_claim_rollback(app_context, monkeypatch):
    session = SessionStub()
    context = context_with_session(app_context, session)
    monkeypatch.setattr(
        "app.bot.handlers.admin.ViolationRecalculationService.recalculate_current_cycle",
        AsyncMock(return_value=ViolationRecalculationResult()),
    )
    callback = FakeCallback("violation_recalculation:confirm", 1)
    callback.message.edit_text.side_effect = RuntimeError("telegram unavailable")

    await violation_recalculation_confirm(callback, context)

    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    text = callback.message.answer.await_args.args[0]
    assert "изменения сохранены" in text
    assert "отменены" not in text


@pytest.mark.asyncio
async def test_recalculation_sends_only_summary_not_per_violation(app_context, monkeypatch):
    session = SessionStub()
    context = context_with_session(app_context, session)
    monkeypatch.setattr(
        "app.bot.handlers.admin.ViolationRecalculationService.recalculate_current_cycle",
        AsyncMock(return_value=ViolationRecalculationResult(created=20)),
    )
    callback = FakeCallback("violation_recalculation:confirm", 1)

    await violation_recalculation_confirm(callback, context)

    callback.message.edit_text.assert_awaited_once()
    callback.message.answer.assert_not_awaited()

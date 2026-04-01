from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.bot.handlers.registration import registration_player_tag, registration_player_token, start_registration
from app.bot.handlers.stats import custom_period_end, custom_period_start, my_stats_entry
from app.bot.states.period import PeriodSelectionStates
from app.bot.states.registration import RegistrationStates
from app.models import CycleBoundary, PlayerAccount, TelegramPlayerLink, TelegramUser
from tests.fakes import FakeMessage, FakeState
from tests.helpers import make_player_profile


@pytest.mark.asyncio
async def test_registration_fsm_flow(app_context, fake_clash_client):
    fake_clash_client.verify_map[("#P2", "GOOD")] = True
    fake_clash_client.players["#P2"] = make_player_profile("#P2", "Alpha")
    state = FakeState()

    start_message = FakeMessage(text="📝 Регистрация")
    await start_registration(start_message, state, app_context)
    assert state.state == str(RegistrationStates.waiting_for_player_tag)

    tag_message = FakeMessage(text="#P2")
    await registration_player_tag(tag_message, state, app_context)
    assert state.state == str(RegistrationStates.waiting_for_player_token)

    token_message = FakeMessage(text="GOOD")
    await registration_player_token(token_message, state, app_context)
    assert state.state is None
    assert "успешно" in token_message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_registration_fsm_stops_for_registered_user(app_context, session_maker):
    async with session_maker() as session:
        tg = TelegramUser(telegram_id=100, username="tester", registered_at=datetime(2026, 1, 1, tzinfo=UTC))
        session.add(tg)
        await session.flush()
        session.add(TelegramPlayerLink(telegram_user_id=tg.id, player_tag="#P2", linked_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await session.commit()

    state = FakeState()
    state.state = str(RegistrationStates.waiting_for_player_tag)
    message = FakeMessage(text="#P8", user_id=100)
    await registration_player_tag(message, state, app_context)
    assert state.state is None
    assert "Вы уже зарегистрированы" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_start_registration_direct_call_is_blocked_for_registered_user(app_context, session_maker):
    async with session_maker() as session:
        tg = TelegramUser(telegram_id=101, username="tester2", registered_at=datetime(2026, 1, 1, tzinfo=UTC))
        session.add(tg)
        await session.flush()
        session.add(TelegramPlayerLink(telegram_user_id=tg.id, player_tag="#P9", linked_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await session.commit()

    state = FakeState()
    message = FakeMessage(text="📝 Регистрация", user_id=101)
    await start_registration(message, state, app_context)
    assert state.state is None
    assert "Вы уже зарегистрированы" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_custom_period_fsm_flow(app_context, session_maker):
    async with session_maker() as session:
        session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
        tg = TelegramUser(telegram_id=100, username="tester", registered_at=datetime(2026, 1, 1, tzinfo=UTC))
        session.add(tg)
        await session.flush()
        session.add(TelegramPlayerLink(telegram_user_id=tg.id, player_tag="#P2", linked_at=datetime(2026, 1, 1, tzinfo=UTC)))
        session.add(
            PlayerAccount(
                player_tag="#P2",
                name="Alpha",
                town_hall=16,
                current_clan_tag="#CLAN",
                current_clan_name="TestClan",
                current_clan_rank=1,
                current_in_clan=True,
                last_seen_in_clan_at=datetime(2026, 4, 1, tzinfo=UTC),
                first_absent_at=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    state = FakeState()
    state._data["selected_player_tag"] = "#P2"
    await custom_period_start(FakeMessage(text="2026-04-01"), state)
    assert state.state == str(PeriodSelectionStates.waiting_for_custom_end)
    end_message = FakeMessage(text="2026-04-02")
    await custom_period_end(end_message, state, app_context)
    assert state.state is None
    assert "Период" in end_message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_my_stats_button_requires_registration(app_context):
    state = FakeState()
    message = FakeMessage(text="📊 Моя статистика", user_id=555)
    await my_stats_entry(message, app_context, state)
    assert "Сначала пройдите регистрацию" in message.answer.await_args.args[0]

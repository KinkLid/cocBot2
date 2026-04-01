from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.bot.handlers.registration import registration_player_tag, registration_player_token, start_registration
from app.bot.handlers.stats import (
    choose_my_stats_account,
    choose_my_stats_period,
    custom_period_end,
    custom_period_start,
    my_stats_entry,
)
from app.bot.states.period import PeriodSelectionStates
from app.bot.states.registration import RegistrationStates
from app.models import CycleBoundary, PlayerAccount, TelegramPlayerLink, TelegramUser
from tests.fakes import FakeCallback, FakeMessage, FakeState
from tests.helpers import make_player_profile


async def _seed_user_with_links(session_maker, user_id: int, tags: list[str]) -> None:
    async with session_maker() as session:
        tg = TelegramUser(telegram_id=user_id, username=f"u{user_id}", registered_at=datetime(2026, 1, 1, tzinfo=UTC))
        session.add(tg)
        await session.flush()
        for tag in tags:
            session.add(TelegramPlayerLink(telegram_user_id=tg.id, player_tag=tag, linked_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await session.commit()


async def _seed_player(session_maker, player_tag: str, in_clan: bool = True) -> None:
    async with session_maker() as session:
        session.add(
            PlayerAccount(
                player_tag=player_tag,
                name="Alpha",
                town_hall=16,
                current_clan_tag="#CLAN" if in_clan else None,
                current_clan_name="TestClan" if in_clan else None,
                current_clan_rank=1 if in_clan else None,
                current_in_clan=in_clan,
                last_seen_in_clan_at=datetime(2026, 4, 1, tzinfo=UTC),
                first_absent_at=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
        )
        await session.commit()


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
async def test_my_stats_button_requires_registration(app_context):
    state = FakeState()
    message = FakeMessage(text="📊 Моя статистика", user_id=555)
    await my_stats_entry(message, app_context, state)
    assert "Сначала пройдите регистрацию" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_my_stats_button_registered_without_links_gets_message(app_context, session_maker):
    await _seed_user_with_links(session_maker, user_id=111, tags=[])
    state = FakeState()
    message = FakeMessage(text="📊 Моя статистика", user_id=111)
    await my_stats_entry(message, app_context, state)
    assert "нет привязанных" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_my_stats_single_account_goes_to_period_choice(app_context, session_maker):
    await _seed_user_with_links(session_maker, user_id=112, tags=["#P2"])
    state = FakeState()
    message = FakeMessage(text="📊 Моя статистика", user_id=112)
    await my_stats_entry(message, app_context, state)
    assert message.answer.await_count == 1
    assert "Выберите период" in message.answer.await_args.args[0]
    assert state._data["selected_player_tag"] == "#P2"


@pytest.mark.asyncio
async def test_my_stats_multiple_accounts_shows_account_choice(app_context, session_maker):
    await _seed_user_with_links(session_maker, user_id=113, tags=["#P2", "#P8"])
    state = FakeState()
    message = FakeMessage(text="📊 Моя статистика", user_id=113)
    await my_stats_entry(message, app_context, state)
    assert "несколько аккаунтов" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_choose_period_current_without_cycle_boundaries_returns_error(app_context, session_maker):
    await _seed_user_with_links(session_maker, user_id=114, tags=["#P2"])
    await _seed_player(session_maker, "#P2", in_clan=True)

    state = FakeState()
    state._data["selected_player_tag"] = "#P2"
    callback = FakeCallback(data="my_stats_period:current", user_id=114)

    await choose_my_stats_period(callback, state, app_context)

    assert "недостаточно данных по циклам" in callback.message.answer.await_args.args[0]
    assert state.state is None


@pytest.mark.asyncio
async def test_choose_period_previous_without_enough_boundaries_returns_error(app_context, session_maker):
    await _seed_user_with_links(session_maker, user_id=115, tags=["#P2"])
    await _seed_player(session_maker, "#P2", in_clan=True)
    async with session_maker() as session:
        session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
        await session.commit()

    state = FakeState()
    state._data["selected_player_tag"] = "#P2"
    callback = FakeCallback(data="my_stats_period:previous", user_id=115)

    await choose_my_stats_period(callback, state, app_context)

    assert "недостаточно данных по циклам" in callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_choose_period_returns_error_when_player_not_in_clan(app_context, session_maker):
    await _seed_user_with_links(session_maker, user_id=116, tags=["#P9"])
    await _seed_player(session_maker, "#P9", in_clan=False)
    async with session_maker() as session:
        session.add_all(
            [
                CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"),
                CycleBoundary(source_key="cwl:2026-04", boundary_at=datetime(2026, 4, 4, tzinfo=UTC), description="b2"),
            ]
        )
        await session.commit()

    state = FakeState()
    state._data["selected_player_tag"] = "#P9"
    callback = FakeCallback(data="my_stats_period:current", user_id=116)

    await choose_my_stats_period(callback, state, app_context)

    assert "игрок сейчас не состоит в клане" in callback.message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_custom_period_invalid_start_date_returns_error_and_keeps_state():
    state = FakeState()
    state._data["selected_player_tag"] = "#P2"
    await state.set_state(PeriodSelectionStates.waiting_for_custom_start)

    message = FakeMessage(text="2026/04/01")
    await custom_period_start(message, state)

    assert "Неверный формат даты" in message.answer.await_args.args[0]
    assert state.state == str(PeriodSelectionStates.waiting_for_custom_start)


@pytest.mark.asyncio
async def test_custom_period_invalid_end_date_returns_error(app_context):
    state = FakeState()
    state._data.update({"selected_player_tag": "#P2", "custom_start": "2026-04-01"})
    await state.set_state(PeriodSelectionStates.waiting_for_custom_end)

    message = FakeMessage(text="2026/04/02")
    await custom_period_end(message, state, app_context)

    assert "Неверный формат даты" in message.answer.await_args.args[0]
    assert state.state == str(PeriodSelectionStates.waiting_for_custom_end)


@pytest.mark.asyncio
async def test_custom_period_end_before_start_returns_error_and_clears_state(app_context):
    state = FakeState()
    state._data.update({"selected_player_tag": "#P2", "custom_start": "2026-04-03"})
    await state.set_state(PeriodSelectionStates.waiting_for_custom_end)

    message = FakeMessage(text="2026-04-02")
    await custom_period_end(message, state, app_context)

    assert "Дата конца периода" in message.answer.await_args.args[0]
    assert state.state is None


@pytest.mark.asyncio
async def test_missing_selected_tag_returns_message_and_clears_state(app_context):
    state = FakeState()
    callback = FakeCallback(data="my_stats_period:current", user_id=117)

    await choose_my_stats_period(callback, state, app_context)

    assert "Сначала выберите игровой аккаунт" in callback.message.answer.await_args.args[0]
    assert state.state is None


@pytest.mark.asyncio
async def test_unexpected_error_is_logged_and_user_gets_safe_message(app_context, caplog, monkeypatch):
    state = FakeState()
    message = FakeMessage(text="📊 Моя статистика", user_id=118)

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.repositories.telegram_user.TelegramUserRepository.get_by_telegram_id", _boom)

    with caplog.at_level("ERROR"):
        await my_stats_entry(message, app_context, state)

    assert "Не удалось показать статистику" in message.answer.await_args.args[0]
    assert any("Ошибка в обработчике кнопки 'Моя статистика'" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_choose_account_updates_selected_player_tag():
    state = FakeState()
    callback = FakeCallback(data="my_stats_account:#P8", user_id=119)

    await choose_my_stats_account(callback, state)

    assert state._data["selected_player_tag"] == "#P8"
    assert callback.answer.await_count == 1

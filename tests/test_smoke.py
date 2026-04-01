from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.bot.handlers.admin import admin_clan_stats, admin_players
from app.bot.handlers.common import clan_chat_link
from app.bot.handlers.start import command_start
from app.models import TelegramPlayerLink, TelegramUser
from tests.fakes import FakeMessage


@pytest.mark.asyncio
async def test_start_command_shows_main_menu(app_context):
    message = FakeMessage(text="/start", user_id=1)
    await command_start(message, app_context)
    message.answer.assert_awaited()
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    assert reply_markup.keyboard[0][0].text == "📝 Регистрация"


@pytest.mark.asyncio
async def test_start_command_hides_registration_for_registered_user(app_context, session_maker):
    async with session_maker() as session:
        tg = TelegramUser(telegram_id=100, username="tester", registered_at=datetime(2026, 1, 1, tzinfo=UTC))
        session.add(tg)
        await session.flush()
        session.add(TelegramPlayerLink(telegram_user_id=tg.id, player_tag="#P2", linked_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await session.commit()

    message = FakeMessage(text="/start", user_id=100)
    await command_start(message, app_context)
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    flat_buttons = [button.text for row in reply_markup.keyboard for button in row]
    assert "📝 Регистрация" not in flat_buttons


@pytest.mark.asyncio
async def test_common_buttons_smoke(app_context):
    message = FakeMessage(text="🔗 Ссылка на чат клана", user_id=100)
    await clan_chat_link(message, app_context)
    message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_admin_buttons_smoke(app_context):
    message_players = FakeMessage(text="👥 Список игроков", user_id=1)
    await admin_players(message_players, app_context)
    assert "Выберите сортировку" in message_players.answer.await_args.args[0]

    message_stats = FakeMessage(text="📈 Статистика клана", user_id=999)
    await admin_clan_stats(message_stats, app_context)
    assert "Недостаточно прав" in message_stats.answer.await_args.args[0]

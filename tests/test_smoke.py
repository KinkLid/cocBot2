from __future__ import annotations

import pytest

from app.bot.handlers.admin import admin_clan_stats, admin_players
from app.bot.handlers.common import clan_chat_link
from app.bot.handlers.start import command_start
from tests.fakes import FakeMessage


@pytest.mark.asyncio
async def test_start_command_shows_main_menu(app_context):
    message = FakeMessage(text="/start", user_id=1)
    await command_start(message, app_context)
    message.answer.assert_awaited()
    reply_markup = message.answer.await_args.kwargs["reply_markup"]
    assert reply_markup.keyboard[0][0].text == "📝 Регистрация"


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

from __future__ import annotations

from datetime import UTC, datetime

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import AppYamlConfig, PollingIntervals, Settings
from app.container import AppContext
from app.db.base import Base
from app.services.auth import AuthService
from app.services.logs import LogService

from app.bot.keyboards.main import main_menu
from app.bot.keyboards.common import admin_player_link_keyboard
from app.bot.handlers.admin import (
    admin_player_link_cancel,
    admin_player_link_receive_telegram_id,
    admin_player_link_select_player,
    admin_player_link_start,
)
from app.bot.states.admin_player_link import AdminPlayerLinkStates
from app.models import PlayerAccount, TelegramPlayerLink, TelegramUser
from app.services.admin_player_link import (
    AdminPlayerLinkService,
    PlayerAlreadyLinkedToAnotherTelegramError,
    PlayerNotAvailableForLinkError,
)
from tests.fakes import FakeCallback, FakeMessage, FakeState, FakeClashApiClient



@pytest.fixture()
def session_maker(tmp_path: Path):
    import asyncio

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}")

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield maker
    asyncio.run(engine.dispose())


@pytest.fixture()
def session(session_maker):
    import asyncio

    async_session = session_maker()
    yield async_session
    asyncio.run(async_session.close())


@pytest.fixture()
def fake_clash_client():
    return FakeClashApiClient()


@pytest.fixture()
def app_context(tmp_path: Path, session_maker, fake_clash_client):
    settings = Settings(
        bot_token="123:TEST",
        clash_api_token="CLASH_TOKEN",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
        config_path=str(tmp_path / "config.yaml"),
        log_file=str(tmp_path / "clanbot.log"),
    )
    config = AppYamlConfig(
        main_clan_tag="#CLAN",
        admin_telegram_ids=[1, 2],
        clan_chat_url="https://t.me/test_clan_chat",
        polling=PollingIntervals(active_war_seconds=90, clan_members_seconds=900, housekeeping_seconds=3600),
        log_level="INFO",
    )
    return AppContext(
        settings=settings,
        config=config,
        session_maker=session_maker,
        clash_client=fake_clash_client,
        auth_service=AuthService(config),
        log_service=LogService(settings.log_file),
        export_dir=Path(settings.log_file).parent / "exports",
    )

NOW = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)


def _texts(markup):
    return [button.text for row in markup.keyboard for button in row]


def _inline_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


async def _add_player(session, tag, name, *, clan="#CLAN", active=True, rank=1):
    player = PlayerAccount(
        player_tag=tag,
        name=name,
        town_hall=16,
        current_clan_tag=clan,
        current_clan_name="Main" if clan else None,
        current_clan_rank=rank,
        current_in_clan=active,
        last_seen_in_clan_at=NOW if active else None,
        first_absent_at=None if active else NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(player)
    await session.flush()
    return player


async def _count_links(session):
    return len((await session.execute(select(TelegramPlayerLink))).scalars().all())


def test_admin_menu_contains_manual_player_link_button():
    texts = _texts(main_menu(is_admin=True, is_registered=True))
    assert "🔗 Привязать игрока" in texts
    assert texts.index("👥 Список игроков") < texts.index("🔗 Привязать игрока") < texts.index("🧾 Разбор вклада")


def test_non_admin_menu_does_not_contain_manual_player_link_button():
    assert "🔗 Привязать игрока" not in _texts(main_menu(is_admin=False, is_registered=True))


def test_admin_player_link_keyboard_has_pagination_and_control_buttons():
    players = [type("P", (), {"current_clan_rank": i, "name": f"P{i}", "player_tag": f"#P{i}"}) for i in range(1, 12)]
    markup = admin_player_link_keyboard(players, page=0)
    buttons = _inline_buttons(markup)
    player_buttons = [b for b in buttons if b.callback_data.startswith("admin_player_link:player:")]
    assert len(player_buttons) == 10
    assert player_buttons[0].text == "1. P1 (#P1)"
    assert player_buttons[0].callback_data == "admin_player_link:player:#P1"
    assert any(b.text == "➡️" and b.callback_data == "admin_player_link:page:1" for b in buttons)
    assert any(b.text == "✏️ Другой Telegram ID" and b.callback_data == "admin_player_link:change_user" for b in buttons)
    assert any(b.text == "❌ Отмена" and b.callback_data == "admin_player_link:cancel" for b in buttons)


def test_admin_link_creates_user_and_link_without_player_token(session, app_context, fake_clash_client):
    import asyncio

    async def _run():
        await _add_player(session, "#P0P0", "Hero")
        result = await AdminPlayerLinkService(session, app_context.config).link_player(telegram_id=555, player_tag="#P0P0")
        assert result.telegram_id == 555
        assert result.player_tag == "#P0P0"
        assert result.player_name == "Hero"
        assert result.already_linked is False
        assert await _count_links(session) == 1
        user = (await session.execute(select(TelegramUser).where(TelegramUser.telegram_id == 555))).scalar_one()
        assert user.username is None
        assert fake_clash_client.verify_map == {}
        assert fake_clash_client.players == {}



    asyncio.run(_run())
def test_admin_link_preserves_existing_telegram_username(session, app_context):
    import asyncio

    async def _run():
        await _add_player(session, "#P0PY", "Hero")
        user = TelegramUser(telegram_id=777, username="old", registered_at=NOW)
        session.add(user)
        await session.flush()
        await AdminPlayerLinkService(session, app_context.config).link_player(telegram_id=777, player_tag="#P0PY")
        await session.refresh(user)
        assert user.username == "old"



    asyncio.run(_run())
def test_admin_link_is_idempotent_for_same_user_and_player(session, app_context):
    import asyncio

    async def _run():
        await _add_player(session, "#P0P2", "Hero")
        first = await AdminPlayerLinkService(session, app_context.config).link_player(telegram_id=888, player_tag="#P0P2")
        second = await AdminPlayerLinkService(session, app_context.config).link_player(telegram_id=888, player_tag="#P0P2")
        assert first.already_linked is False
        assert second.already_linked is True
        assert await _count_links(session) == 1



    asyncio.run(_run())
def test_admin_link_allows_multiple_players_for_one_telegram_user(session, app_context):
    import asyncio

    async def _run():
        await _add_player(session, "#P0P9", "One")
        await _add_player(session, "#P0P8", "Two", rank=2)
        service = AdminPlayerLinkService(session, app_context.config)
        await service.link_player(telegram_id=999, player_tag="#P0P9")
        await service.link_player(telegram_id=999, player_tag="#P0P8")
        assert await _count_links(session) == 2



    asyncio.run(_run())
def test_admin_link_rejects_player_linked_to_another_telegram_user(session, app_context):
    import asyncio

    async def _run():
        await _add_player(session, "#P0PJ", "Hero")
        service = AdminPlayerLinkService(session, app_context.config)
        await service.link_player(telegram_id=111, player_tag="#P0PJ")
        with pytest.raises(PlayerAlreadyLinkedToAnotherTelegramError) as exc:
            await service.link_player(telegram_id=222, player_tag="#P0PJ")
        assert exc.value.owner_telegram_ids == [111]
        assert await _count_links(session) == 1



    asyncio.run(_run())
def test_admin_link_rejects_absent_or_foreign_clan_player(session, app_context):
    import asyncio

    async def _run():
        await _add_player(session, "#P0PC", "Absent", active=False, clan=None)
        await _add_player(session, "#P0PV", "Foreign", clan="#OTHER")
        service = AdminPlayerLinkService(session, app_context.config)
        for tag in ["#P0PL", "#P0PC", "#P0PV"]:
            with pytest.raises(PlayerNotAvailableForLinkError):
                await service.link_player(telegram_id=333, player_tag=tag)
        assert await _count_links(session) == 0



    asyncio.run(_run())
def test_non_admin_cannot_start_manual_player_link(app_context):
    import asyncio

    async def _run():
        message = FakeMessage("🔗 Привязать игрока", user_id=999)
        state = FakeState()
        await admin_player_link_start(message, state, app_context)
        message.answer.assert_awaited_with("⛔ Недостаточно прав")
        assert await state.get_state() is None



    asyncio.run(_run())
def test_admin_player_link_start_requests_telegram_id(app_context):
    import asyncio

    async def _run():
        message = FakeMessage("🔗 Привязать игрока", user_id=1)
        state = FakeState()
        await admin_player_link_start(message, state, app_context)
        assert await state.get_state() == str(AdminPlayerLinkStates.waiting_for_telegram_id)
        assert "Введите числовой Telegram ID" in message.answer.await_args.args[0]



    asyncio.run(_run())
def test_invalid_telegram_id_keeps_waiting_state(app_context):
    import asyncio

    async def _run():
        for text in ["abc", "-1", "0"]:
            message = FakeMessage(text, user_id=1)
            state = FakeState()
            await state.set_state(AdminPlayerLinkStates.waiting_for_telegram_id)
            await admin_player_link_receive_telegram_id(message, state, app_context)
            assert await state.get_state() == str(AdminPlayerLinkStates.waiting_for_telegram_id)
            assert "Telegram ID должен состоять только из цифр" in message.answer.await_args.args[0]



    asyncio.run(_run())
def test_valid_telegram_id_shows_active_clan_players(session_maker, app_context):
    import asyncio

    async def _run():
        async with session_maker() as session:
            await _add_player(session, "#P0P8", "Active")
            await _add_player(session, "#P0P9", "Foreign", clan="#OTHER", rank=2)
            await session.commit()
        message = FakeMessage("12345", user_id=1)
        state = FakeState()
        await state.set_state(AdminPlayerLinkStates.waiting_for_telegram_id)
        await admin_player_link_receive_telegram_id(message, state, app_context)
        assert (await state.get_data())["target_telegram_id"] == 12345
        assert await state.get_state() == str(AdminPlayerLinkStates.choosing_player)
        markup = message.answer.await_args.kwargs["reply_markup"]
        texts = [b.text for b in _inline_buttons(markup)]
        assert any("Active" in t for t in texts)
        assert not any("Foreign" in t for t in texts)



    asyncio.run(_run())
def test_admin_player_selection_creates_link_and_clears_state(session_maker, app_context):
    import asyncio

    async def _run():
        async with session_maker() as session:
            await _add_player(session, "#P0Q0", "Chosen")
            await session.commit()
        state = FakeState()
        await state.set_state(AdminPlayerLinkStates.choosing_player)
        await state.update_data(target_telegram_id=444)
        callback = FakeCallback("admin_player_link:player:#P0Q0", user_id=1)
        await admin_player_link_select_player(callback, state, app_context)
        assert await state.get_state() is None
        assert "привязан к Telegram ID 444" in callback.message.edit_text.await_args.args[0]
        async with session_maker() as session:
            assert await _count_links(session) == 1



    asyncio.run(_run())
def test_admin_player_selection_reports_existing_foreign_owner(session_maker, app_context):
    import asyncio

    async def _run():
        async with session_maker() as session:
            await _add_player(session, "#P0QY", "Chosen")
            await AdminPlayerLinkService(session, app_context.config).link_player(telegram_id=111, player_tag="#P0QY")
        state = FakeState()
        await state.set_state(AdminPlayerLinkStates.choosing_player)
        await state.update_data(target_telegram_id=222)
        callback = FakeCallback("admin_player_link:player:#P0QY", user_id=1)
        await admin_player_link_select_player(callback, state, app_context)
        assert await state.get_state() == str(AdminPlayerLinkStates.choosing_player)
        callback.answer.assert_awaited_with("Этот игровой аккаунт уже привязан к Telegram ID: 111", show_alert=True)
        async with session_maker() as session:
            assert await _count_links(session) == 1



    asyncio.run(_run())
def test_admin_player_link_cancel_clears_state(app_context):
    import asyncio

    async def _run():
        state = FakeState()
        await state.set_state(AdminPlayerLinkStates.choosing_player)
        callback = FakeCallback("admin_player_link:cancel", user_id=1)
        await admin_player_link_cancel(callback, state, app_context)
        assert await state.get_state() is None
        assert callback.message.edit_text.await_args.args[0] == "❌ Ручная привязка отменена."
        assert callback.message.answer.await_args.args[0] == "Административное меню"

    asyncio.run(_run())

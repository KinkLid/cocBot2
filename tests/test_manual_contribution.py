from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.keyboards.main import main_menu
from app.db.base import Base
from app.models import ManualContributionAdjustment, PlayerAccount
from app.repositories.manual_contribution import ManualContributionRepository
from app.services.contribution_breakdown import ContributionBreakdownService
from app.services.dev_contribution import DevContributionService

NOW = datetime(2026, 6, 21, 18, 30, tzinfo=UTC)

async def _db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'manual.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, maker

async def _seed(session, tag="#P1", name="Player", rank=1, clan="#CLAN"):
    p = PlayerAccount(player_tag=tag, name=name, town_hall=16, current_clan_tag=clan, current_clan_name="Clan", current_clan_rank=rank, current_in_clan=True, created_at=NOW, updated_at=NOW)
    session.add(p)
    await session.flush()
    return p

def test_manual_adjustment_repository_and_validation(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            player = await _seed(session)
            repo = ManualContributionRepository(session)
            adj = await repo.add_manual_adjustment(player.id, "#CLAN", 25, "Помощь", 1, "admin", NOW, "tok-25")
            assert adj.id is not None
            await repo.add_manual_adjustment(player.id, "#CLAN", 15, "Еще помощь", 1, None, NOW + timedelta(minutes=1), "tok-15")
            await repo.add_manual_adjustment(player.id, "#OTHER", 99, "Другой клан", 1, None, NOW, "tok-other")
            with pytest.raises(ValueError):
                await repo.add_manual_adjustment(player.id, "#CLAN", 0, "ok", 1, None, NOW, "bad-0")
            with pytest.raises(ValueError):
                await repo.add_manual_adjustment(player.id, "#CLAN", -1, "ok", 1, None, NOW, "bad-neg")
            with pytest.raises(ValueError):
                await repo.add_manual_adjustment(player.id, "#CLAN", 1, " ", 1, None, NOW, "bad-comment")
            totals = await repo.manual_adjustment_totals([player.id], "#CLAN", NOW - timedelta(seconds=1), NOW + timedelta(days=1))
            assert totals[player.id] == 40
            rows = await repo.manual_adjustments_for_player(player.id, "#CLAN", NOW + timedelta(seconds=30), NOW + timedelta(days=1))
            assert [r.points for r in rows] == [15]
        await engine.dispose()
    asyncio.run(run())

def test_manual_adjustment_db_check_constraint(tmp_path):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            player = await _seed(session)
            session.add(ManualContributionAdjustment(player_id=player.id, clan_tag="#CLAN", points=0, comment="bad", created_by_telegram_id=1, created_at=NOW, operation_token="bad-db"))
            with pytest.raises(IntegrityError):
                await session.flush()
        await engine.dispose()
    asyncio.run(run())

def test_contribution_and_breakdown_include_manual_adjustments(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            p1 = await _seed(session, "#P1", "Alpha", 1)
            p2 = await _seed(session, "#P2", "Beta", 2)
            repo = ManualContributionRepository(session)
            await repo.add_manual_adjustment(p1.id, "#CLAN", 30, "Помощь", 1, "admin", NOW, "tok-p1")
            await repo.add_manual_adjustment(p2.id, "#CLAN", 50, "Больше", 1, "admin", NOW, "tok-p2")
            await repo.add_manual_adjustment(p1.id, "#CLAN", 100, "Старое", 1, "admin", NOW - timedelta(days=2), "tok-old")
            await session.commit()
            period = SimpleNamespace(start=NOW - timedelta(days=1), end=NOW + timedelta(minutes=1))
            ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(period)
            assert [(r.player_tag, r.score, r.manual_adjustment) for r in ranking] == [("#P2", 50.0, 50), ("#P1", 30.0, 30)]
            breakdown = await ContributionBreakdownService(session, app_yaml_config).build_player_breakdown("#P1", period)
            assert breakdown.manual_adjustment_total == 30
            text = ContributionBreakdownService.format_detailed_breakdown(breakdown)
            assert "➕ Ручные начисления: +30" in text
            assert "@admin" in text
        await engine.dispose()
    asyncio.run(run())

def test_manual_contribution_button_admin_only():
    admin_texts = [b.text for row in main_menu(True, True).keyboard for b in row]
    user_texts = [b.text for row in main_menu(False, True).keyboard for b in row]
    assert "➕ Начислить баллы" in admin_texts
    assert "➕ Начислить баллы" not in user_texts

from unittest.mock import patch
from sqlalchemy import func, select
from app.bot.handlers.admin import manual_contribution_callback
from app.bot.states.manual_contribution import ManualContributionStates
from app.models import CycleBoundary
from tests.fakes import FakeCallback, FakeState
from app.services.auth import AuthService


def test_manual_contribution_confirm_total_includes_new_and_previous(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            player = await _seed(session)
            session.add(CycleBoundary(source_key="cycle", boundary_at=NOW - timedelta(hours=1), description="cycle"))
            await ManualContributionRepository(session).add_manual_adjustment(player.id, "#CLAN", 15, "Старое", 1, "admin", NOW - timedelta(minutes=10), "old-token")
            await session.commit()

        state = FakeState()
        await state.set_state(ManualContributionStates.confirming)
        await state.update_data(player_id=1, player_name="Player", player_tag="#P1", points=25, comment="Новые баллы", operation_token="new-token")
        callback = FakeCallback("manual_contribution:confirm:new-token", user_id=1, username="admin")
        ctx = SimpleNamespace(config=app_yaml_config, session_maker=maker, clash_client=None, auth_service=AuthService(app_yaml_config))
        with patch("app.bot.handlers.admin.utcnow", side_effect=[NOW, NOW]):
            await manual_contribution_callback(callback, state, ctx)

        text = callback.message.answer.call_args.args[0]
        assert "Ручных баллов игрока за текущий цикл: +40" in text
        assert await state.get_state() is None
        async with maker() as session:
            assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 2
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_confirm_first_total_is_not_zero(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            player = await _seed(session)
            session.add(CycleBoundary(source_key="cycle", boundary_at=NOW - timedelta(hours=1), description="cycle"))
            await session.commit()

        state = FakeState()
        await state.set_state(ManualContributionStates.confirming)
        await state.update_data(player_id=1, player_name="Player", player_tag="#P1", points=25, comment="Новые баллы", operation_token="first-token")
        callback = FakeCallback("manual_contribution:confirm:first-token", user_id=1, username="admin")
        ctx = SimpleNamespace(config=app_yaml_config, session_maker=maker, clash_client=None, auth_service=AuthService(app_yaml_config))
        with patch("app.bot.handlers.admin.utcnow", side_effect=[NOW, NOW]):
            await manual_contribution_callback(callback, state, ctx)

        text = callback.message.answer.call_args.args[0]
        assert "Ручных баллов игрока за текущий цикл: +25" in text
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_parallel_confirm_is_idempotent(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            await _seed(session)
            session.add(CycleBoundary(source_key="cycle", boundary_at=NOW - timedelta(hours=1), description="cycle"))
            await session.commit()

        async def call_once():
            state = FakeState()
            await state.set_state(ManualContributionStates.confirming)
            await state.update_data(player_id=1, player_name="Player", player_tag="#P1", points=25, comment="Новые баллы", operation_token="race-token")
            callback = FakeCallback("manual_contribution:confirm:race-token", user_id=1, username="admin")
            with patch("app.bot.handlers.admin.utcnow", return_value=NOW):
                await manual_contribution_callback(callback, state, SimpleNamespace(config=app_yaml_config, session_maker=maker, clash_client=None, auth_service=AuthService(app_yaml_config)))
            return callback

        callbacks = await asyncio.gather(call_once(), call_once())
        async with maker() as session:
            assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 1
            total = await ManualContributionRepository(session).manual_adjustment_total_for_player(1, "#CLAN", NOW - timedelta(hours=1), NOW + timedelta(seconds=1))
            assert total == 25
        messages = [cb.message.answer.call_args.args[0] for cb in callbacks if cb.message.answer.call_args]
        answers = [cb.answer.call_args.args[0] for cb in callbacks if cb.answer.call_args and cb.answer.call_args.args]
        assert len(messages) == 1
        assert "Баллы уже были начислены." in answers
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_stale_token_does_not_create_adjustment(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            await _seed(session)
            await session.commit()
        state = FakeState()
        await state.set_state(ManualContributionStates.confirming)
        await state.update_data(player_id=1, player_name="Player", player_tag="#P1", points=25, comment="Новые баллы", operation_token="fresh-token")
        callback = FakeCallback("manual_contribution:confirm:old-token", user_id=1)
        await manual_contribution_callback(callback, state, SimpleNamespace(config=app_yaml_config, session_maker=maker, clash_client=None, auth_service=AuthService(app_yaml_config)))
        assert callback.answer.call_args.args[0] == "Эта операция устарела. Начните начисление заново."
        async with maker() as session:
            assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 0
        await engine.dispose()
    asyncio.run(run())

from app.bot.handlers.admin import manual_contribution_start, manual_contribution_points, manual_contribution_comment
from app.bot.keyboards.common import manual_contribution_players_keyboard
from tests.fakes import FakeMessage


def _ctx(config, maker):
    return SimpleNamespace(config=config, session_maker=maker, clash_client=None, auth_service=AuthService(config))


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_manual_contribution_access_denied_does_not_mutate_fsm_or_db(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        state = FakeState()
        await state.set_state(ManualContributionStates.entering_points)
        await state.update_data(player_id=123, player_tag="#P", player_name="P")
        ctx = _ctx(app_yaml_config, maker)

        cb = FakeCallback("manual_contribution:player:1", user_id=999)
        await manual_contribution_callback(cb, state, ctx)
        assert cb.answer.call_args.args[0] == "⛔ Недостаточно прав"
        assert await state.get_state() == str(ManualContributionStates.entering_points)

        msg = FakeMessage("25", user_id=999)
        await manual_contribution_points(msg, state, ctx)
        assert msg.answer.call_args.args[0] == "⛔ Недостаточно прав"
        assert await state.get_state() == str(ManualContributionStates.entering_points)
        assert (await state.get_data())["player_id"] == 123
        async with maker() as session:
            assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 0
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_player_selection_filters_sorts_and_stores_stable_id(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            beta = await _seed(session, "#B", "Beta", 2)
            alpha = await _seed(session, "#A", "Alpha", 1)
            left = await _seed(session, "#L", "Left", 3); left.current_in_clan = False
            other = await _seed(session, "#O", "Other", 4, clan="#OTHER")
            await session.commit()
        cb = FakeCallback(f"manual_contribution:player:{alpha.id}", user_id=1)
        state = FakeState()
        await manual_contribution_start(FakeMessage("➕ Начислить баллы", user_id=1), state, _ctx(app_yaml_config, maker))
        markup = cb.message.answer.call_args
        async with maker() as session:
            players = await ManualContributionRepository(session).current_main_clan_players("#CLAN")
        assert [p.player_name for p in players] == ["Alpha", "Beta"]
        keyboard = manual_contribution_players_keyboard(players, 0)
        callbacks = [b.callback_data for b in _buttons(keyboard) if b.callback_data.startswith("manual_contribution:player:")]
        assert callbacks == [f"manual_contribution:player:{alpha.id}", f"manual_contribution:player:{beta.id}"]
        assert all("Alpha" not in c and "Beta" not in c for c in callbacks)
        await manual_contribution_callback(cb, state, _ctx(app_yaml_config, maker))
        data = await state.get_data()
        assert (data["player_id"], data["player_tag"], data["player_name"]) == (alpha.id, "#A", "Alpha")
        bad = FakeCallback("manual_contribution:player:999999", user_id=1)
        await manual_contribution_callback(bad, state, _ctx(app_yaml_config, maker))
        assert bad.answer.call_args.args[0] == "⚠️ Игрок недоступен"
        async with maker() as session:
            db_alpha = await session.get(PlayerAccount, alpha.id); db_alpha.current_in_clan = False; await session.commit()
        stale = FakeCallback(f"manual_contribution:player:{alpha.id}", user_id=1)
        await manual_contribution_callback(stale, state, _ctx(app_yaml_config, maker))
        assert stale.answer.call_args.args[0] == "⚠️ Игрок недоступен"
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_pagination_50_players_and_callback_size(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            for i in range(1, 51):
                await _seed(session, f"#P{i}", f"Player {i:02d}", i)
            await session.commit()
            players = await ManualContributionRepository(session).current_main_clan_players("#CLAN")
        seen = []
        for page in range(5):
            kb = manual_contribution_players_keyboard(players, page)
            player_buttons = [b for b in _buttons(kb) if b.callback_data.startswith("manual_contribution:player:")]
            assert len(player_buttons) <= 12
            seen.extend(b.callback_data for b in player_buttons)
            assert all(len(b.callback_data.encode()) <= 64 for b in _buttons(kb))
            texts = [b.text for b in _buttons(kb)]
            if page == 0: assert "⬅️" not in texts and "➡️" in texts
            if page == 4: assert "➡️" not in texts and "⬅️" in texts
        assert len(seen) == 50 and len(set(seen)) == 50
        bad = FakeCallback("manual_contribution:page:bad", user_id=1)
        await manual_contribution_callback(bad, FakeState(), _ctx(app_yaml_config, maker))
        assert bad.answer.call_args.args[0] == "⚠️ Некорректная операция"
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("value,expected", [("1",1),("25",25),("10000",10000),(" 25 ",25)])
def test_manual_contribution_points_valid_values(value, expected, tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path); state = FakeState(); await state.set_state(ManualContributionStates.entering_points); await state.update_data(player_id=1, player_tag="#P1", player_name="P")
        msg = FakeMessage(value, user_id=1)
        await manual_contribution_points(msg, state, _ctx(app_yaml_config, maker))
        assert await state.get_state() == str(ManualContributionStates.entering_comment)
        assert (await state.get_data())["points"] == expected
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("value", ["", "0", "-1", "10001", "1.5", "1,5", "abc", "+25", "9" * 200])
def test_manual_contribution_points_invalid_values_keep_state(value, tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path); state = FakeState(); await state.set_state(ManualContributionStates.entering_points); await state.update_data(player_id=1, player_tag="#P1", player_name="P")
        msg = FakeMessage(value, user_id=1)
        await manual_contribution_points(msg, state, _ctx(app_yaml_config, maker))
        assert msg.answer.call_args.args[0] == "Введите целое количество баллов от 1 до 10000."
        assert await state.get_state() == str(ManualContributionStates.entering_points)
        assert (await state.get_data())["player_tag"] == "#P1"
        async with maker() as session: assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 0
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("comment,stored", [("abc","abc"),("x"*500,"x"*500),("  a  b  ","a  b"),("a\nb","a\nb")])
def test_manual_contribution_comment_valid_values(comment, stored, tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path); state = FakeState(); await state.set_state(ManualContributionStates.entering_comment); await state.update_data(player_id=1, player_tag="#P1", player_name="P", points=25)
        msg = FakeMessage(comment, user_id=1)
        await manual_contribution_comment(msg, state, _ctx(app_yaml_config, maker))
        data = await state.get_data()
        assert await state.get_state() == str(ManualContributionStates.confirming)
        assert data["comment"] == stored and data["operation_token"]
        text = msg.answer.call_args.args[0]
        assert "P (#P1)" in text and "Баллы: +25" in text and f"Причина: {stored}" in text
        buttons = _buttons(msg.answer.call_args.kwargs["reply_markup"])
        assert {"✅ Начислить", "⬅️ Назад", "❌ Отмена"}.issubset({b.text for b in buttons})
        assert any(data["operation_token"] in b.callback_data and len(b.callback_data.encode()) <= 64 for b in buttons)
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("comment", ["", "   ", "a", "ab", "x"*501])
def test_manual_contribution_comment_invalid_values_keep_state(comment, tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path); state = FakeState(); await state.set_state(ManualContributionStates.entering_comment); await state.update_data(player_id=1, player_tag="#P1", player_name="P", points=25)
        msg = FakeMessage(comment, user_id=1)
        await manual_contribution_comment(msg, state, _ctx(app_yaml_config, maker))
        assert msg.answer.call_args.args[0] == "Комментарий должен содержать от 3 до 500 символов."
        assert await state.get_state() == str(ManualContributionStates.entering_comment)
        assert (await state.get_data())["points"] == 25
        async with maker() as session: assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 0
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_navigation_cancel_and_stale_callbacks(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            p = await _seed(session); session.add(CycleBoundary(source_key="cycle", boundary_at=NOW - timedelta(hours=1), description="cycle")); await session.commit()
        ctx = _ctx(app_yaml_config, maker); state = FakeState()
        await state.set_state(ManualContributionStates.choosing_player)
        back = FakeCallback("manual_contribution:back", user_id=1); await manual_contribution_callback(back, state, ctx); assert await state.get_state() is None
        await state.set_state(ManualContributionStates.entering_points); b1=FakeCallback("manual_contribution:back", user_id=1); await manual_contribution_callback(b1,state,ctx); assert await state.get_state()==str(ManualContributionStates.choosing_player)
        await state.set_state(ManualContributionStates.entering_comment); b2=FakeCallback("manual_contribution:back", user_id=1); await manual_contribution_callback(b2,state,ctx); assert await state.get_state()==str(ManualContributionStates.entering_points)
        await state.set_state(ManualContributionStates.confirming); b3=FakeCallback("manual_contribution:back", user_id=1); await manual_contribution_callback(b3,state,ctx); assert await state.get_state()==str(ManualContributionStates.entering_comment)
        await state.update_data(player_id=p.id, player_name="Player", player_tag="#P1", points=10)
        m1=FakeMessage("first", user_id=1); await manual_contribution_comment(m1,state,ctx); old=(await state.get_data())["operation_token"]
        await state.set_state(ManualContributionStates.entering_comment); await state.update_data(points=20)
        m2=FakeMessage("second", user_id=1); await manual_contribution_comment(m2,state,ctx); new=(await state.get_data())["operation_token"]
        assert old != new
        stale=FakeCallback(f"manual_contribution:confirm:{old}", user_id=1); await manual_contribution_callback(stale,state,ctx); assert stale.answer.call_args.args[0] == "Эта операция устарела. Начните начисление заново."
        cancel=FakeCallback("manual_contribution:cancel", user_id=1); await manual_contribution_callback(cancel,state,ctx); assert await state.get_state() is None
        post=FakeCallback(f"manual_contribution:confirm:{new}", user_id=1); await manual_contribution_callback(post,state,ctx); assert post.answer.call_args.args[0] == "Эта операция устарела. Начните начисление заново."
        async with maker() as session: assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 0
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_malformed_and_foreign_tokens_are_safe(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path); state=FakeState(); await state.set_state(ManualContributionStates.confirming); await state.update_data(operation_token="good", player_id=1, points=1, comment="abc")
        for data in ["manual_contribution:confirm", "manual_contribution:confirm:", "manual_contribution:confirm:" + "x"*65, "manual_contribution:confirm:bad"]:
            cb=FakeCallback(data, user_id=1); await manual_contribution_callback(cb,state,_ctx(app_yaml_config,maker)); assert cb.answer.call_args.args[0] in {"⚠️ Некорректная операция", "Эта операция устарела. Начните начисление заново."}
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_full_success_persists_expected_fields(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            p = await _seed(session); session.add(CycleBoundary(source_key="cycle", boundary_at=NOW - timedelta(hours=1), description="cycle")); await ManualContributionRepository(session).add_manual_adjustment(p.id,"#CLAN",5,"old",1,"admin",NOW-timedelta(minutes=30),"old-sum"); await ManualContributionRepository(session).add_manual_adjustment(p.id,"#CLAN",99,"prev",1,"admin",NOW-timedelta(days=2),"prev"); await ManualContributionRepository(session).add_manual_adjustment(p.id,"#OTHER",77,"other",1,"admin",NOW,"other"); await session.commit()
        state=FakeState(); await state.set_state(ManualContributionStates.confirming); await state.update_data(player_id=1, player_name="Player", player_tag="#P1", points=25, comment="Новые баллы", operation_token="success-token")
        cb=FakeCallback("manual_contribution:confirm:success-token", user_id=1, username="admin")
        with patch("app.bot.handlers.admin.utcnow", side_effect=[NOW, NOW]): await manual_contribution_callback(cb,state,_ctx(app_yaml_config,maker))
        assert await state.get_state() is None and "✅ Баллы начислены" in cb.message.answer.call_args.args[0] and "+30" in cb.message.answer.call_args.args[0]
        async with maker() as session:
            rows=(await session.scalars(select(ManualContributionAdjustment).where(ManualContributionAdjustment.operation_token=="success-token"))).all(); assert len(rows)==1
            adj=rows[0]; assert (adj.player_id, adj.clan_tag, adj.points, adj.comment, adj.created_by_telegram_id, adj.created_by_username, adj.created_at.replace(tzinfo=UTC), adj.operation_token)==(1,"#CLAN",25,"Новые баллы",1,"admin",NOW,"success-token")
            ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(SimpleNamespace(start=NOW-timedelta(hours=1), end=NOW+timedelta(minutes=1)))
            assert ranking[0].manual_adjustment == 30
            text = ContributionBreakdownService.format_detailed_breakdown(await ContributionBreakdownService(session, app_yaml_config).build_player_breakdown("#P1", SimpleNamespace(start=NOW-timedelta(hours=1), end=NOW+timedelta(minutes=1))))
            assert "Новые баллы" in text
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_repeated_and_distinct_tokens(tmp_path, app_yaml_config):
    async def run():
        engine, maker = await _db(tmp_path)
        async with maker() as session:
            await _seed(session); session.add(CycleBoundary(source_key="cycle", boundary_at=NOW-timedelta(hours=1), description="cycle")); await session.commit()
        ctx=_ctx(app_yaml_config,maker)
        async def confirm(token):
            st=FakeState(); await st.set_state(ManualContributionStates.confirming); await st.update_data(player_id=1, player_name="Player", player_tag="#P1", points=25, comment="same", operation_token=token)
            cb=FakeCallback(f"manual_contribution:confirm:{token}", user_id=1)
            with patch("app.bot.handlers.admin.utcnow", return_value=NOW): await manual_contribution_callback(cb,st,ctx)
            return cb
        first=await confirm("dup-token"); second=await confirm("dup-token")
        assert "✅ Баллы начислены" in first.message.answer.call_args.args[0]
        assert second.answer.call_args.args[0] == "Баллы уже были начислены."
        await asyncio.gather(confirm("distinct-1"), confirm("distinct-2"))
        async with maker() as session:
            assert await session.scalar(select(func.count(ManualContributionAdjustment.id))) == 3
            assert await ManualContributionRepository(session).manual_adjustment_total_for_player(1,"#CLAN",NOW-timedelta(hours=1),NOW+timedelta(seconds=1)) == 75
        await engine.dispose()
    asyncio.run(run())


def test_manual_contribution_db_error_rolls_back_logs_and_keeps_consistent_state(tmp_path, app_yaml_config, caplog):
    class BrokenSession:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): self.rolled_back = exc is not None
        async def scalar(self, stmt): return None
        async def flush(self): raise RuntimeError("database is down")
        def add(self, obj): pass
    class BrokenMaker:
        def __init__(self): self.sessions=[]
        def __call__(self): s=BrokenSession(); self.sessions.append(s); return s
    async def run():
        maker=BrokenMaker(); state=FakeState(); await state.set_state(ManualContributionStates.confirming); await state.update_data(player_id=1, player_name="Player", player_tag="#P1", points=25, comment="comment", operation_token="db-error")
        cb=FakeCallback("manual_contribution:confirm:db-error", user_id=1)
        with caplog.at_level("ERROR"):
            await manual_contribution_callback(cb,state,_ctx(app_yaml_config,maker))
        assert cb.message.answer.call_args.args[0] == "❌ Не удалось начислить баллы. Попробуйте позже."
        assert "✅ Баллы начислены" not in cb.message.answer.call_args.args[0]
        assert await state.get_state() == str(ManualContributionStates.confirming)
        assert "Failed to create manual contribution adjustment" in caplog.text
    asyncio.run(run())

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

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
            adj = await repo.add_manual_adjustment(player.id, "#CLAN", 25, "Помощь", 1, "admin", NOW)
            assert adj.id is not None
            await repo.add_manual_adjustment(player.id, "#CLAN", 15, "Еще помощь", 1, None, NOW + timedelta(minutes=1))
            await repo.add_manual_adjustment(player.id, "#OTHER", 99, "Другой клан", 1, None, NOW)
            with pytest.raises(ValueError):
                await repo.add_manual_adjustment(player.id, "#CLAN", 0, "ok", 1, None, NOW)
            with pytest.raises(ValueError):
                await repo.add_manual_adjustment(player.id, "#CLAN", -1, "ok", 1, None, NOW)
            with pytest.raises(ValueError):
                await repo.add_manual_adjustment(player.id, "#CLAN", 1, " ", 1, None, NOW)
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
            session.add(ManualContributionAdjustment(player_id=player.id, clan_tag="#CLAN", points=0, comment="bad", created_by_telegram_id=1, created_at=NOW))
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
            await repo.add_manual_adjustment(p1.id, "#CLAN", 30, "Помощь", 1, "admin", NOW)
            await repo.add_manual_adjustment(p2.id, "#CLAN", 50, "Больше", 1, "admin", NOW)
            await repo.add_manual_adjustment(p1.id, "#CLAN", 100, "Старое", 1, "admin", NOW - timedelta(days=2))
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

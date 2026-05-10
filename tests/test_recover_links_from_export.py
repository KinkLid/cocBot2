from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import PlayerAccount, TelegramPlayerLink, TelegramUser
from scripts.recover_links_from_export import recover_links


def run(coro):
    return asyncio.run(coro)


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    session = maker()
    return engine, session


def test_recovery_creates_user_player_and_link():
    async def scenario():
        engine, session = await _make_session()
        try:
            stats = await recover_links(session, [{"player_tag": "#P1", "player_name": "Alpha", "town_hall": 16, "telegram_id": 101, "telegram_username": "alpha", "registered_at": "2026-01-01T10:00:00Z"}])
            await session.commit()
            assert stats.created_telegram_users == 1
            assert stats.created_player_accounts == 1
            assert stats.created_links == 1
        finally:
            await session.close()
            await engine.dispose()

    run(scenario())


def test_recovery_is_idempotent():
    async def scenario():
        engine, session = await _make_session()
        try:
            players = [{"player_tag": "#P1", "player_name": "Alpha", "town_hall": 16, "telegram_id": 101}]
            await recover_links(session, players)
            await session.commit()
            await recover_links(session, players)
            await session.commit()
            assert await session.scalar(select(func.count(TelegramUser.id))) == 1
            assert await session.scalar(select(func.count(PlayerAccount.id))) == 1
            assert await session.scalar(select(func.count(TelegramPlayerLink.id))) == 1
        finally:
            await session.close()
            await engine.dispose()

    run(scenario())


def test_skip_without_telegram_id_and_dry_run():
    async def scenario():
        engine, session = await _make_session()
        try:
            stats = await recover_links(session, [{"player_tag": "#P2", "player_name": "NoTG", "town_hall": 15, "telegram_id": None}])
            assert stats.skipped_without_telegram_id == 1
            await recover_links(session, [{"player_tag": "#P9", "player_name": "Z", "town_hall": 13, "telegram_id": 909}])
            await session.rollback()
            assert await session.scalar(select(func.count(TelegramUser.id))) == 0
        finally:
            await session.close()
            await engine.dispose()

    run(scenario())


def test_multi_account_and_conflict():
    async def scenario():
        engine, session = await _make_session()
        try:
            stats = await recover_links(session, [
                {"player_tag": "#P1", "player_name": "A", "town_hall": 16, "telegram_id": 101},
                {"player_tag": "#P2", "player_name": "B", "town_hall": 15, "telegram_id": 101},
            ])
            await session.commit()
            assert stats.created_telegram_users == 1
            assert stats.created_links == 2
            conflict_stats = await recover_links(session, [{"player_tag": "#P1", "player_name": "A", "town_hall": 16, "telegram_id": 202}])
            await session.commit()
            assert conflict_stats.skipped_conflicts == 1
            assert await session.scalar(select(func.count(TelegramPlayerLink.id))) == 2
        finally:
            await session.close()
            await engine.dispose()

    run(scenario())

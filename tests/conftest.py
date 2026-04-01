from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import AppYamlConfig, PollingIntervals, Settings
from app.container import AppContext
from app.db.base import Base
from app.models import *  # noqa: F401,F403
from app.services.auth import AuthService
from app.services.logs import LogService
from tests.fakes import FakeClashApiClient


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token="123:TEST",
        clash_api_token="CLASH_TOKEN",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
        config_path=str(tmp_path / "config.yaml"),
        log_file=str(tmp_path / "clanbot.log"),
    )


@pytest.fixture()
def app_yaml_config() -> AppYamlConfig:
    return AppYamlConfig(
        main_clan_tag="#CLAN",
        admin_telegram_ids=[1, 2],
        clan_chat_url="https://t.me/test_clan_chat",
        polling=PollingIntervals(active_war_seconds=90, clan_members_seconds=900, housekeeping_seconds=3600),
        log_level="INFO",
    )


@pytest.fixture()
async def session_maker(settings: Settings):
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield maker
    await engine.dispose()


@pytest.fixture()
async def session(session_maker: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_maker() as session:
        yield session


@pytest.fixture()
def fake_clash_client() -> FakeClashApiClient:
    return FakeClashApiClient()


@pytest.fixture()
def app_context(settings: Settings, app_yaml_config: AppYamlConfig, session_maker, fake_clash_client: FakeClashApiClient) -> AppContext:
    return AppContext(
        settings=settings,
        config=app_yaml_config,
        session_maker=session_maker,
        clash_client=fake_clash_client,
        auth_service=AuthService(app_yaml_config),
        log_service=LogService(settings.log_file),
        export_dir=Path(settings.log_file).parent / "exports",
    )


@pytest.fixture()
def now() -> datetime:
    return datetime(2026, 4, 1, 12, 0, tzinfo=UTC)

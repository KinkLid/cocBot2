from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import func, select

from app.models import PlayerAccount, ReturnEvent
from app.services.startup_sync import StartupSyncService
from tests.fakes import FakeSender
from tests.helpers import make_clan_member


@pytest.mark.asyncio
async def test_startup_sync_saves_clan_roster_and_players(session, app_context, fake_clash_client):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1), make_clan_member("#P8", "Bravo", 2)]
    sender = FakeSender()

    report = await StartupSyncService(app_context, sender).run()

    assert report.clan_sync_ok is True
    players = list((await session.execute(select(PlayerAccount).order_by(PlayerAccount.player_tag))).scalars())
    assert [player.player_tag for player in players] == ["#P2", "#P8"]
    assert all(player.current_in_clan for player in players)


@pytest.mark.asyncio
async def test_startup_sync_is_idempotent_without_duplicates(session, app_context, fake_clash_client):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1), make_clan_member("#P8", "Bravo", 2)]
    sender = FakeSender()
    service = StartupSyncService(app_context, sender)

    await service.run()
    await service.run()

    total = await session.scalar(select(func.count(PlayerAccount.id)))
    assert total == 2


@pytest.mark.asyncio
async def test_startup_sync_handles_departed_and_returned_players(session, app_context, fake_clash_client):
    sender = FakeSender()
    service = StartupSyncService(app_context, sender)

    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.run()

    fake_clash_client.members = []
    await service.run()
    departed = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P2"))
    assert departed is not None
    assert departed.current_in_clan is False

    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.run()

    event = await session.scalar(select(ReturnEvent).where(ReturnEvent.player_tag == "#P2"))
    assert event is not None


@pytest.mark.asyncio
async def test_startup_sync_retries_and_logs_temporary_api_failure(app_context, fake_clash_client, caplog):
    sender = FakeSender()
    calls = 0

    async def flaky_get_members(clan_tag: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary Clash API failure")
        return [make_clan_member("#P2", "Alpha", 1)]

    fake_clash_client.get_clan_members = flaky_get_members
    caplog.set_level(logging.INFO)

    report = await StartupSyncService(app_context, sender, max_attempts=3, base_backoff_seconds=0.01).run()

    assert report.clan_sync_ok is True
    assert calls == 2
    assert "Startup clan sync failed" in caplog.text
    assert "Startup clan sync completed" in caplog.text


@pytest.mark.asyncio
async def test_startup_sync_partial_failure_is_logged_and_predictable(app_context, fake_clash_client, caplog):
    sender = FakeSender()
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]

    async def broken_current_war(clan_tag: str):
        raise RuntimeError("war endpoint is down")

    fake_clash_client.get_current_war = broken_current_war
    caplog.set_level(logging.INFO)

    report = await StartupSyncService(app_context, sender).run()

    assert report.clan_sync_ok is True
    assert report.war_sync_ok is False
    assert "Startup war sync failed" in caplog.text


@pytest.mark.asyncio
async def test_main_run_calls_startup_sync(monkeypatch):
    from app import main as main_module

    startup_run = AsyncMock(return_value=SimpleNamespace(clan_sync_ok=True, war_sync_ok=True, members_processed=1))
    startup_service = SimpleNamespace(run=startup_run)

    class FakeBot:
        def __init__(self, *args, **kwargs):
            self.session = SimpleNamespace(close=AsyncMock())

    fake_scheduler = SimpleNamespace(start=Mock(), shutdown=Mock())
    fake_dispatcher = SimpleNamespace(start_polling=AsyncMock(side_effect=RuntimeError("stop loop")))
    fake_engine = SimpleNamespace(dispose=AsyncMock())
    fake_clash = SimpleNamespace(close=AsyncMock())
    fake_context = SimpleNamespace(clash_client=fake_clash)

    monkeypatch.setattr(main_module, "Settings", lambda: SimpleNamespace(load_yaml_config=lambda: SimpleNamespace(log_level="INFO"), bot_token="x", clash_api_token="y", log_file="/tmp/log", clash_request_timeout_seconds=5))
    monkeypatch.setattr(main_module, "create_engine_and_sessionmaker", lambda settings: (fake_engine, object()))
    monkeypatch.setattr(main_module, "build_context", lambda settings, config, session_maker: fake_context)
    monkeypatch.setattr(main_module, "Bot", FakeBot)
    monkeypatch.setattr(main_module, "create_dispatcher", lambda _ctx: fake_dispatcher)
    monkeypatch.setattr(main_module, "create_scheduler", lambda _ctx, _sender: fake_scheduler)
    monkeypatch.setattr(main_module, "StartupSyncService", lambda _ctx, _sender: startup_service)
    monkeypatch.setattr(main_module, "configure_logging", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="stop loop"):
        await main_module.run()

    startup_run.assert_awaited_once()

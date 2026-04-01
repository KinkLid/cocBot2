from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import CycleBoundary, DepartedPlayerArchive, PlayerAccount, ReturnEvent
from app.services.clan_sync import ClanSyncService
from app.services.notifications import AdminNotifier
from app.services.stats import StatsService
from tests.fakes import FakeSender
from tests.helpers import make_clan_member


@pytest.mark.asyncio
async def test_clan_roster_is_saved(session, fake_clash_client, app_yaml_config):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1), make_clan_member("#P8", "Bravo", 2)]
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())

    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    players = list((await session.execute(select(PlayerAccount).order_by(PlayerAccount.player_tag))).scalars())
    assert [player.player_tag for player in players] == ["#P2", "#P8"]
    assert all(player.current_in_clan for player in players)


@pytest.mark.asyncio
async def test_player_exit_is_detected(session, fake_clash_client, app_yaml_config):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1), make_clan_member("#P8", "Bravo", 2)]
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, notifier)
    await service.sync_members()

    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.sync_members()

    player = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P8"))
    assert player is not None
    assert player.current_in_clan is False
    assert player.first_absent_at is not None


@pytest.mark.asyncio
async def test_player_is_ignored_after_absence_and_not_returned_in_stats(session, fake_clash_client, app_yaml_config):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1), make_clan_member("#P8", "Bravo", 2)]
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, notifier)
    await service.sync_members()

    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.sync_members()

    session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="prev"))
    await session.commit()

    stats = await StatsService(session, app_yaml_config).clan_stats(datetime(2026, 3, 6, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC))
    assert "#P2" in stats.text
    assert "#P8" not in stats.text


@pytest.mark.asyncio
async def test_player_is_fully_purged_after_full_cycle_absence(session, fake_clash_client, app_yaml_config, monkeypatch):
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, notifier)
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.sync_members()

    player = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P2"))
    player.current_in_clan = False
    player.first_absent_at = datetime(2026, 3, 1, tzinfo=UTC)
    player.last_seen_in_clan_at = datetime(2026, 3, 1, tzinfo=UTC)
    session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
    session.add(CycleBoundary(source_key="cwl:2026-04", boundary_at=datetime(2026, 4, 4, tzinfo=UTC), description="b2"))
    await session.commit()

    fake_clash_client.members = []
    monkeypatch.setattr("app.services.clan_sync.utcnow", lambda: datetime(2026, 4, 5, tzinfo=UTC))
    await service.sync_members()

    assert await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P2")) is None
    archive = await session.scalar(select(DepartedPlayerArchive).where(DepartedPlayerArchive.player_tag == "#P2"))
    assert archive is not None


@pytest.mark.asyncio
async def test_player_return_is_recorded(session, fake_clash_client, app_yaml_config):
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, notifier)

    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.sync_members()
    fake_clash_client.members = []
    await service.sync_members()
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.sync_members()

    event = await session.scalar(select(ReturnEvent).where(ReturnEvent.player_tag == "#P2"))
    assert event is not None
    assert event.was_purged is False


@pytest.mark.asyncio
async def test_admins_are_notified_about_player_return(session, fake_clash_client, app_yaml_config):
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, notifier)

    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.sync_members()
    fake_clash_client.members = []
    await service.sync_members()
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    await service.sync_members()

    assert len(sender.sent) == 2
    assert all("Игрок вернулся" in text for _, text in sender.sent)

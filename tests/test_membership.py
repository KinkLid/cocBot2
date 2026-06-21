from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import CycleBoundary, DepartedPlayerArchive, ClanMembershipHistory, PlayerAccount, PlayerDonationSnapshot, ReturnEvent
from app.services.clan_sync import ClanSyncService
from app.services.notifications import AdminNotifier
from app.services.stats import StatsService
from tests.fakes import FakeSender
from tests.helpers import make_clan_member, make_player_profile


@pytest.mark.asyncio
async def test_clan_roster_is_saved(session, fake_clash_client, app_yaml_config):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1), make_clan_member("#P8", "Bravo", 2)]
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())

    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    players = list((await session.execute(select(PlayerAccount).order_by(PlayerAccount.player_tag))).scalars())
    assert [player.player_tag for player in players] == ["#P2", "#P8"]
    assert all(player.current_in_clan for player in players)


@pytest.mark.asyncio
async def test_member_profile_failure_does_not_abort_roster_sync(session, fake_clash_client, app_yaml_config, caplog):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1), make_clan_member("#P8", "Bravo", 2)]
    fake_clash_client.players["#P8"] = make_player_profile("#P8", "Bravo")
    fake_clash_client.players["#P8"].donations = 123
    fake_clash_client.players["#P8"].donations_received = 45
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())
    caplog.set_level("WARNING")

    processed = await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    assert processed == 2
    players = list((await session.execute(select(PlayerAccount).order_by(PlayerAccount.player_tag))).scalars())
    assert [player.player_tag for player in players] == ["#P2", "#P8"]
    assert all(player.current_in_clan for player in players)
    memberships = list((await session.execute(select(ClanMembershipHistory).order_by(ClanMembershipHistory.player_id))).scalars())
    assert len(memberships) == 2
    snapshots = list((await session.execute(select(PlayerDonationSnapshot))).scalars())
    assert [snapshot.player_tag for snapshot in snapshots] == ["#P8"]
    assert snapshots[0].donations == 123
    assert snapshots[0].donations_received == 45
    assert "Failed to load player profile for donation snapshot: #P2" in caplog.text


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


def _make_members(start: int, end: int):
    return [make_clan_member(f"#P{i:02d}", f"Player{i:02d}", i) for i in range(start, end + 1)]


class FailingSender:
    async def __call__(self, chat_id: int, text: str) -> None:
        raise RuntimeError("Telegram send failed")


async def _active_tags(session):
    players = list((await session.execute(select(PlayerAccount).where(PlayerAccount.current_in_clan.is_(True)))).scalars())
    return {player.player_tag for player in players}


@pytest.mark.asyncio
async def test_roster_reconciliation_survives_telegram_failure_on_return(session, fake_clash_client, app_yaml_config, caplog):
    stale_members = _make_members(1, 45)
    fake_clash_client.members = stale_members
    fake_clash_client.clan["members"] = 45
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, AdminNotifier(session, app_yaml_config, FakeSender()))
    await service.sync_members()

    player = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P30"))
    assert player is not None
    await service.players.mark_absent(player, datetime(2026, 4, 1, tzinfo=UTC))
    await session.commit()

    api_members = _make_members(20, 69)
    api_tags = {member.tag for member in api_members}
    fake_clash_client.members = api_members
    fake_clash_client.clan["members"] = 50
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, AdminNotifier(session, app_yaml_config, FailingSender()))
    caplog.set_level("WARNING")

    processed = await service.sync_members()

    assert processed == 50
    assert await _active_tags(session) == api_tags
    assert "Failed to send admin notification" in caplog.text
    old_departed = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P01"))
    assert old_departed is not None
    assert old_departed.current_in_clan is False
    returned_player = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P30"))
    assert returned_player is not None
    assert returned_player.current_in_clan is True
    new_player = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P69"))
    assert new_player is not None
    assert new_player.current_in_clan is True


@pytest.mark.asyncio
async def test_partial_clash_roster_response_does_not_modify_database(session, fake_clash_client, app_yaml_config):
    initial_members = _make_members(1, 50)
    fake_clash_client.members = initial_members
    fake_clash_client.clan["members"] = 50
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, AdminNotifier(session, app_yaml_config, FakeSender()))
    await service.sync_members()
    before_tags = await _active_tags(session)

    fake_clash_client.members = _make_members(1, 45)
    with pytest.raises(ValueError, match="Incomplete clan roster response"):
        await service.sync_members()

    assert await _active_tags(session) == before_tags
    assert await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P46")) is not None
    assert await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == "#P60")) is None


@pytest.mark.asyncio
async def test_donation_snapshot_failure_does_not_rollback_roster(session, fake_clash_client, app_yaml_config, monkeypatch, caplog):
    fake_clash_client.members = _make_members(1, 45)
    fake_clash_client.clan["members"] = 45
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, AdminNotifier(session, app_yaml_config, FakeSender()))
    await service.sync_members()

    api_members = _make_members(20, 69)
    api_tags = {member.tag for member in api_members}
    fake_clash_client.members = api_members
    fake_clash_client.clan["members"] = 50
    for member in api_members:
        fake_clash_client.players[member.tag] = make_player_profile(member.tag, member.name)

    original = service.donations.record_snapshot

    async def broken_record_snapshot(**kwargs):
        if kwargs["player_tag"] == "#P20":
            raise RuntimeError("donation snapshot failed")
        return await original(**kwargs)

    monkeypatch.setattr(service.donations, "record_snapshot", broken_record_snapshot)
    caplog.set_level("WARNING")

    await service.sync_members()

    assert await _active_tags(session) == api_tags
    assert "Failed to record donation snapshot: #P20" in caplog.text


@pytest.mark.asyncio
async def test_purge_failure_does_not_rollback_roster(session, fake_clash_client, app_yaml_config, monkeypatch, caplog):
    fake_clash_client.members = _make_members(1, 45)
    fake_clash_client.clan["members"] = 45
    service = ClanSyncService(session, fake_clash_client, app_yaml_config, AdminNotifier(session, app_yaml_config, FakeSender()))
    await service.sync_members()

    api_members = _make_members(20, 69)
    api_tags = {member.tag for member in api_members}
    fake_clash_client.members = api_members
    fake_clash_client.clan["members"] = 50

    async def broken_purge(now):
        raise RuntimeError("purge failed")

    monkeypatch.setattr(service, "_purge_players_absent_full_cycle", broken_purge)
    caplog.set_level("ERROR")

    await service.sync_members()

    assert await _active_tags(session) == api_tags
    assert "Failed to purge players absent for a full cycle" in caplog.text

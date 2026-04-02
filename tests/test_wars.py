from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Attack, CycleBoundary, Violation, War, WarParticipant
from app.models.enums import WarType
from app.services.clan_sync import ClanSyncService
from app.services.notifications import AdminNotifier
from app.services.stats import StatsService
from app.services.war_sync import WarSyncService
from tests.fakes import FakeSender
from tests.helpers import make_clan_member, make_cwl_group, make_regular_war


@pytest.mark.asyncio
async def test_regular_war_is_saved(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=1))
    fake_clash_client.current_war = make_regular_war(start=start)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    war = await session.scalar(select(War))
    assert war is not None
    assert war.war_type == WarType.REGULAR


@pytest.mark.asyncio
async def test_cwl_war_is_saved_as_separate_war(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    start = datetime(2026, 4, 2, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=13))
    fake_clash_client.cwl_group = make_cwl_group("2026-04", ["#PQLY"])
    cwl_war = make_regular_war(start=start)
    cwl_war.war_type = WarType.CWL
    cwl_war.league_group_id = "#CLAN:2026-04"
    cwl_war.cwl_season = "2026-04"
    fake_clash_client.cwl_wars["#PQLY"] = cwl_war

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    war = await session.scalar(select(War))
    assert war is not None
    assert war.war_type == WarType.CWL


@pytest.mark.asyncio
async def test_participation_is_determined_from_roster(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=1))
    fake_clash_client.current_war = make_regular_war(start=start, include_attack=False)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    participant = await session.scalar(select(WarParticipant).where(WarParticipant.player_tag == "#P2"))
    assert participant is not None
    assert participant.map_position == 12


@pytest.mark.asyncio
async def test_attack_is_saved_and_stars_counted(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()
    session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
    await session.commit()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=1))
    fake_clash_client.current_war = make_regular_war(start=start, stars=3)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    attack_count = await session.scalar(select(func.count(Attack.id)))
    assert attack_count == 1
    stats = await StatsService(session, app_yaml_config).clan_stats(datetime(2026, 3, 6, tzinfo=UTC), datetime(2026, 4, 2, tzinfo=UTC))
    assert "⭐ Звёзд: 3" in stats.text


@pytest.mark.asyncio
async def test_violation_in_first_12_hours_is_recorded(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()
    session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
    await session.commit()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=1))
    fake_clash_client.current_war = make_regular_war(start=start, attacker_position=12, defender_position=5)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    violation = await session.scalar(select(Violation))
    assert violation is not None
    assert "выше своей позиции" in violation.reason_text


@pytest.mark.asyncio
async def test_no_violation_after_12_hours(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=13))
    fake_clash_client.current_war = make_regular_war(start=start, attacker_position=12, defender_position=5)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    assert await session.scalar(select(Violation)) is None


@pytest.mark.asyncio
async def test_violation_when_attacking_above_self(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=2))
    fake_clash_client.current_war = make_regular_war(start=start, attacker_position=12, defender_position=11)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    violation = await session.scalar(select(Violation))
    assert violation.code.value == "above_self"


@pytest.mark.asyncio
async def test_violation_when_attacking_more_than_10_positions_lower(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    notifier = AdminNotifier(session, app_yaml_config, FakeSender())
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=2))
    fake_clash_client.current_war = make_regular_war(start=start, attacker_position=12, defender_position=23)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    violation = await session.scalar(select(Violation))
    assert violation.code.value == "too_low"


@pytest.mark.asyncio
async def test_violation_notifications_are_not_duplicated(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()
    session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
    await session.commit()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=2))
    fake_clash_client.current_war = make_regular_war(start=start, attacker_position=12, defender_position=5)
    service = WarSyncService(session, fake_clash_client, app_yaml_config, notifier)

    await service.sync_all()
    await service.sync_all()

    assert len(sender.sent) == 2
    assert await session.scalar(select(func.count(Violation.id))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attacker_position", "defender_position", "hours_after_start", "expected_violation"),
    [
        (26, 26, 1, False),
        (26, 25, 1, True),
        (26, 36, 1, False),
        (26, 37, 1, True),
        (1, 1, 1, False),
        (1, 11, 1, False),
        (1, 12, 1, True),
        (26, 1, 13, False),
    ],
)
async def test_violation_boundaries_in_first_12_hours(
    session,
    fake_clash_client,
    app_yaml_config,
    monkeypatch,
    attacker_position,
    defender_position,
    hours_after_start,
    expected_violation,
):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()
    session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
    await session.commit()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=hours_after_start))
    fake_clash_client.current_war = make_regular_war(
        start=start,
        attacker_position=attacker_position,
        defender_position=defender_position,
    )

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    violation_count = await session.scalar(select(func.count(Violation.id)))
    assert (violation_count > 0) is expected_violation


@pytest.mark.asyncio
async def test_allowed_attack_does_not_create_violation_or_notify_admins(session, fake_clash_client, app_yaml_config, monkeypatch):
    fake_clash_client.members = [make_clan_member("#P2", "Alpha", 1)]
    sender = FakeSender()
    notifier = AdminNotifier(session, app_yaml_config, sender)
    await ClanSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_members()
    session.add(CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"))
    await session.commit()

    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr("app.services.war_sync.utcnow", lambda: start + timedelta(hours=2))
    fake_clash_client.current_war = make_regular_war(start=start, attacker_position=26, defender_position=26)

    await WarSyncService(session, fake_clash_client, app_yaml_config, notifier).sync_all()

    assert await session.scalar(select(func.count(Violation.id))) == 0
    assert len(sender.sent) == 0

from __future__ import annotations

import logging

import pytest
from sqlalchemy import func, select

from app.models import PlayerCapitalContributionSnapshot
from app.schemas.dto import CapitalRaidParticipantDTO, CapitalRaidSeasonDTO, PlayerProfileDTO
from app.services.capital_raid_sync import CapitalRaidSyncService


@pytest.mark.asyncio
async def test_sync_finished_creates_capital_snapshot_records(session, fake_clash_client, app_yaml_config):
    async def _seasons(clan_tag, limit=10):
        return [CapitalRaidSeasonDTO(
            state="ended",
            startTime="20260510T000000.000Z",
            endTime="20260512T000000.000Z",
            members=[CapitalRaidParticipantDTO(tag="#P1", name="P1", attacks=6, attackLimit=6, bonusAttackLimit=1, capitalResourcesLooted=1000)],
        )]
    fake_clash_client.get_capital_raid_seasons = _seasons
    fake_clash_client.players["#P1"] = PlayerProfileDTO(tag="#P1", name="P1", townHallLevel=16, clanCapitalContributions=777)

    await CapitalRaidSyncService(session, fake_clash_client, app_yaml_config).sync_finished()

    count = await session.scalar(select(func.count(PlayerCapitalContributionSnapshot.id)))
    snapshot = await session.scalar(select(PlayerCapitalContributionSnapshot))
    assert count == 1
    assert snapshot.value == 777


@pytest.mark.asyncio
async def test_sync_finished_repeat_does_not_duplicate_snapshot_for_same_weekend(session, fake_clash_client, app_yaml_config):
    season = CapitalRaidSeasonDTO(
        state="ended",
        startTime="20260510T000000.000Z",
        endTime="20260512T000000.000Z",
        members=[CapitalRaidParticipantDTO(tag="#P1", name="P1", attacks=6, attackLimit=6, bonusAttackLimit=1, capitalResourcesLooted=1000)],
    )
    async def _seasons(clan_tag, limit=10):
        return [season]
    fake_clash_client.get_capital_raid_seasons = _seasons
    fake_clash_client.players["#P1"] = PlayerProfileDTO(tag="#P1", name="P1", townHallLevel=16, clanCapitalContributions=777)

    service = CapitalRaidSyncService(session, fake_clash_client, app_yaml_config)
    await service.sync_finished()
    await service.sync_finished()

    count = await session.scalar(select(func.count(PlayerCapitalContributionSnapshot.id)))
    assert count == 1


@pytest.mark.asyncio
async def test_sync_finished_logs_summary_counts(session, fake_clash_client, app_yaml_config, caplog):
    async def _seasons(clan_tag, limit=10):
        return [
            CapitalRaidSeasonDTO(
                state="ended",
                startTime="20260501T000000.000Z",
                endTime="20260503T000000.000Z",
                members=[CapitalRaidParticipantDTO(tag="#P1", name="P1", attacks=6, attackLimit=6, bonusAttackLimit=1, capitalResourcesLooted=1000)],
            ),
            CapitalRaidSeasonDTO(
                state="ended",
                startTime="20260508T000000.000Z",
                endTime="20260510T000000.000Z",
                members=[CapitalRaidParticipantDTO(tag="#P2", name="P2", attacks=5, attackLimit=6, bonusAttackLimit=0, capitalResourcesLooted=700)],
            ),
        ]

    fake_clash_client.get_capital_raid_seasons = _seasons
    fake_clash_client.players["#P1"] = PlayerProfileDTO(tag="#P1", name="P1", townHallLevel=16, clanCapitalContributions=777)
    fake_clash_client.players["#P2"] = PlayerProfileDTO(tag="#P2", name="P2", townHallLevel=16, clanCapitalContributions=555)
    caplog.set_level(logging.DEBUG)

    service = CapitalRaidSyncService(session, fake_clash_client, app_yaml_config)
    await service.sync_finished()
    await service.sync_finished()

    assert "Capital raid sync: api_total=2, ended=2, created=2, updated=0, backfilled=0, participants_saved=2, snapshots_saved=2" in caplog.text
    assert "Capital raid sync: api_total=2, ended=2, created=0, updated=2, backfilled=0, participants_saved=2, snapshots_saved=0" in caplog.text
    assert "Capital raid season processing: raid_season_id=" in caplog.text


@pytest.mark.asyncio
async def test_sync_finished_logs_warning_when_api_has_more_ended_than_db(session, fake_clash_client, app_yaml_config, caplog):
    async def _seasons(clan_tag, limit=10):
        return [
            CapitalRaidSeasonDTO(state="ended", startTime="20260501T000000.000Z", endTime="20260503T000000.000Z", members=[]),
            CapitalRaidSeasonDTO(state="ended", startTime="20260508T000000.000Z", endTime="20260510T000000.000Z", members=[]),
        ]

    fake_clash_client.get_capital_raid_seasons = _seasons
    caplog.set_level(logging.WARNING)

    service = CapitalRaidSyncService(session, fake_clash_client, app_yaml_config)
    original_count_completed = service.repo.count_completed_weekends

    async def _count_completed_stub(clan_tag: str) -> int:
        return 1

    service.repo.count_completed_weekends = _count_completed_stub
    await service.sync_finished()
    service.repo.count_completed_weekends = original_count_completed

    assert "Capital raid sync warning: API returned 2 ended weekends, but only 1 completed weekend is present in DB after sync" in caplog.text


@pytest.mark.asyncio
async def test_sync_finished_backfills_existing_weekend_without_participants(session, fake_clash_client, app_yaml_config):
    season = CapitalRaidSeasonDTO(state="ended", startTime="20260510T000000.000Z", endTime="20260512T000000.000Z", members=[CapitalRaidParticipantDTO(tag="#P1", name="P1", attacks=6, attackLimit=6, bonusAttackLimit=1, capitalResourcesLooted=1000, districtsDestroyed=2)])
    async def _seasons(clan_tag, limit=10):
        return [season]
    fake_clash_client.get_capital_raid_seasons = _seasons
    fake_clash_client.players["#P1"] = PlayerProfileDTO(tag="#P1", name="P1", townHallLevel=16, clanCapitalContributions=777)
    service = CapitalRaidSyncService(session, fake_clash_client, app_yaml_config)
    await service.sync_finished()
    await session.execute("DELETE FROM capital_raid_participants")
    await session.commit()
    await service.sync_finished()
    count = await session.scalar(select(func.count()).select_from(PlayerCapitalContributionSnapshot))
    assert count == 2

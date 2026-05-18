from __future__ import annotations

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

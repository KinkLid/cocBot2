from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models import CapitalRaidParticipant, CapitalRaidWeekend, PlayerCapitalContributionSnapshot
from app.services.capital_raid_contribution import CapitalRaidContributionService


def _weekend(start_day: int, end_day: int) -> CapitalRaidWeekend:
    return CapitalRaidWeekend(
        clan_tag="#CLAN", raid_season_id=f"s{start_day}", state="ended",
        start_time=datetime(2026, 5, start_day, tzinfo=UTC), end_time=datetime(2026, 5, end_day, tzinfo=UTC),
        total_loot=0, total_attacks=0, enemy_districts_destroyed=0, offensive_reward=0, defensive_reward=0,
        processed_at=datetime(2026, 5, end_day + 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_dev_capital_no_weekends(session, app_yaml_config):
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, flag = await service.build_current_cycle_ranking(period)
    assert service.format_current_cycle_ranking(period, ranking, flag) == "⚠️ По клановой столице за текущий цикл пока нет данных."


@pytest.mark.asyncio
async def test_dev_capital_formula_and_destroy_unavailable(session, app_yaml_config):
    w = _weekend(1, 3)
    session.add(w); await session.flush()
    session.add(CapitalRaidParticipant(weekend_id=w.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=6, attack_limit=6, bonus_attacks=1, districts_destroyed=0, capital_resources_looted=21403, clan_capital_contributions_snapshot=0))
    session.add_all([
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026,5,1,tzinfo=UTC), value=1000),
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026,5,3,tzinfo=UTC), value=13000),
    ])
    await session.commit()
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, flag = await service.build_current_cycle_ranking(period)
    assert flag is False
    assert ranking[0]["score"] == pytest.approx(17.0)
    text = service.format_current_cycle_ranking(period, ranking, flag)
    assert "добиваний: —" in text


@pytest.mark.asyncio
async def test_dev_capital_destroy_available_and_penalty(session, app_yaml_config):
    w = _weekend(1, 3)
    session.add(w); await session.flush()
    session.add_all([
        CapitalRaidParticipant(weekend_id=w.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=4, attack_limit=6, bonus_attacks=0, districts_destroyed=1, capital_resources_looted=5000, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w.id, player_id=None, player_tag="#B", player_name="Beta", attacks=6, attack_limit=6, bonus_attacks=0, districts_destroyed=3, capital_resources_looted=5000, clan_capital_contributions_snapshot=0),
    ])
    await session.commit()
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, flag = await service.build_current_cycle_ranking(period)
    assert flag is True
    assert ranking[0]["player_name"] == "Beta"

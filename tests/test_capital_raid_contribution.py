from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models import CapitalRaidParticipant, CapitalRaidWeekend, PlayerCapitalContributionSnapshot
from app.services.capital_raid_contribution import CapitalRaidContributionService


def _weekend(start_day: int, end_day: int | None, raid_season_id: str) -> CapitalRaidWeekend:
    return CapitalRaidWeekend(
        clan_tag="#CLAN", raid_season_id=raid_season_id, state="ended" if end_day else "ongoing",
        start_time=datetime(2026, 5, start_day, tzinfo=UTC), end_time=(datetime(2026, 5, end_day, tzinfo=UTC) if end_day else None),
        total_loot=0, total_attacks=0, enemy_districts_destroyed=0, offensive_reward=0, defensive_reward=0,
        processed_at=datetime(2026, 5, (end_day or start_day) + 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_dev_capital_no_weekends(session, app_yaml_config):
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, flag, stats, _ = await service.build_current_cycle_ranking(period)
    assert service.format_current_cycle_ranking(period, ranking, flag, stats) == "⚠️ По клановой столице за текущий цикл пока нет данных."


@pytest.mark.asyncio
async def test_dev_capital_aggregates_completed_only(session, app_yaml_config):
    w1 = _weekend(1, 3, "s1")
    w2 = _weekend(8, 10, "s2")
    w3 = _weekend(15, None, "s3")
    session.add_all([w1, w2, w3]); await session.flush()
    session.add_all([
        CapitalRaidParticipant(weekend_id=w1.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=5, attack_limit=6, bonus_attacks=1, districts_destroyed=1, capital_resources_looted=10000, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w2.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=6, attack_limit=6, bonus_attacks=0, districts_destroyed=2, capital_resources_looted=15000, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w3.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=6, attack_limit=6, bonus_attacks=0, districts_destroyed=9, capital_resources_looted=999999, clan_capital_contributions_snapshot=0),
    ])
    session.add_all([
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026,5,1,tzinfo=UTC), value=1000),
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026,5,10,tzinfo=UTC), value=21000),
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026,5,20,tzinfo=UTC), value=50000),
    ])
    await session.commit()

    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, _, stats, last_end = await service.build_current_cycle_ranking(period)
    assert stats.completed_weekends == 2
    assert stats.weekends_with_participants == 2
    assert last_end == datetime(2026, 5, 10, tzinfo=UTC)
    assert ranking[0]["attacks"] == 11
    assert ranking[0]["capital_resources_looted"] == 25000
    assert ranking[0]["districts_destroyed"] == 3
    assert ranking[0]["invested_gold"] == 20000


@pytest.mark.asyncio
async def test_dev_capital_single_completed_raid_builds_report(session, app_yaml_config):
    w = _weekend(1, 3, "s1")
    session.add(w); await session.flush()
    session.add(CapitalRaidParticipant(weekend_id=w.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=6, attack_limit=6, bonus_attacks=1, districts_destroyed=0, capital_resources_looted=21403, clan_capital_contributions_snapshot=0))
    await session.commit()
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, flag, stats, _ = await service.build_current_cycle_ranking(period)
    text = service.format_current_cycle_ranking(period, ranking, flag, stats)
    assert "📦 Завершенных рейдов в текущем цикле: 1" in text
    assert "✅ Рейдов с данными участников: 1" in text


@pytest.mark.asyncio
async def test_dev_capital_completed_without_participants_message(session, app_yaml_config):
    w = _weekend(1, 3, "s1")
    session.add(w)
    await session.commit()

    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 5, 30, tzinfo=UTC))
    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, flag, stats, _ = await service.build_current_cycle_ranking(period)
    assert service.format_current_cycle_ranking(period, ranking, flag, stats) == "⚠️ В текущем цикле есть завершенные рейды столицы, но по ним нет данных участников."

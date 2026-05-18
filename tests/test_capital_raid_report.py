from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import CapitalRaidParticipant, CapitalRaidWeekend, PlayerCapitalContributionSnapshot
from app.services.capital_raid_report import CapitalRaidReportService


def _weekend(season: str, start_day: int, end_day: int) -> CapitalRaidWeekend:
    return CapitalRaidWeekend(
        clan_tag="#CLAN",
        raid_season_id=season,
        state="ended",
        start_time=datetime(2026, 5, start_day, tzinfo=UTC),
        end_time=datetime(2026, 5, end_day, tzinfo=UTC),
        total_loot=0,
        total_attacks=0,
        enemy_districts_destroyed=0,
        offensive_reward=0,
        defensive_reward=0,
        processed_at=datetime(2026, 5, end_day + 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_build_recent_weekends_report_when_no_data(session, app_yaml_config):
    text = await CapitalRaidReportService(session, app_yaml_config).build_recent_weekends_report(1)
    assert text == "⚠️ По клановой столице пока нет сохраненных данных."


@pytest.mark.asyncio
async def test_build_recent_weekends_report_returns_error_when_requested_more_than_available(session, app_yaml_config):
    session.add(_weekend("s1", 1, 3))
    await session.commit()
    text = await CapitalRaidReportService(session, app_yaml_config).build_recent_weekends_report(2)
    assert text == "⚠️ В базе сейчас доступно только 1 завершенных рейдов."


@pytest.mark.asyncio
async def test_build_recent_weekends_report_aggregates_one_weekend(session, app_yaml_config):
    w1 = _weekend("s1", 1, 3)
    session.add(w1)
    await session.flush()
    session.add_all([
        CapitalRaidParticipant(weekend_id=w1.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=4, attack_limit=6, bonus_attacks=1, capital_resources_looted=1000, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w1.id, player_id=None, player_tag="#B", player_name="Beta", attacks=2, attack_limit=6, bonus_attacks=0, capital_resources_looted=500, clan_capital_contributions_snapshot=0),
    ])
    session.add_all([
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026, 5, 3, 0, tzinfo=UTC), value=100),
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026, 5, 4, 0, tzinfo=UTC), value=250),
    ])
    await session.commit()

    text = await CapitalRaidReportService(session, app_yaml_config).build_recent_weekends_report(1)
    assert "📚 Последние 1 рейдов" in text
    assert "1. Alpha — атак: 4, бонусных: 1, налутал: 1000, вложил: 150" in text


@pytest.mark.asyncio
async def test_build_recent_weekends_report_aggregates_three_weekends_and_sorts(session, app_yaml_config):
    w1, w2, w3 = _weekend("s1", 1, 3), _weekend("s2", 8, 10), _weekend("s3", 15, 17)
    session.add_all([w1, w2, w3])
    await session.flush()
    session.add_all([
        CapitalRaidParticipant(weekend_id=w1.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=1, attack_limit=6, bonus_attacks=0, capital_resources_looted=100, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w2.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=3, attack_limit=6, bonus_attacks=1, capital_resources_looted=300, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w3.id, player_id=None, player_tag="#A", player_name="Alpha", attacks=1, attack_limit=6, bonus_attacks=1, capital_resources_looted=50, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w1.id, player_id=None, player_tag="#B", player_name="Beta", attacks=5, attack_limit=6, bonus_attacks=1, capital_resources_looted=450, clan_capital_contributions_snapshot=0),
        CapitalRaidParticipant(weekend_id=w2.id, player_id=None, player_tag="#C", player_name="Aardvark", attacks=4, attack_limit=6, bonus_attacks=0, capital_resources_looted=450, clan_capital_contributions_snapshot=0),
    ])
    session.add_all([
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026, 5, 3, 0, tzinfo=UTC), value=10),
        PlayerCapitalContributionSnapshot(player_tag="#A", clan_tag="#CLAN", observed_at=datetime(2026, 5, 20, 0, tzinfo=UTC), value=40),
        PlayerCapitalContributionSnapshot(player_tag="#B", clan_tag="#CLAN", observed_at=datetime(2026, 5, 18, 0, tzinfo=UTC), value=60),
        PlayerCapitalContributionSnapshot(player_tag="#B", clan_tag="#CLAN", observed_at=datetime(2026, 5, 19, 0, tzinfo=UTC), value=65),
    ])
    await session.commit()

    text = await CapitalRaidReportService(session, app_yaml_config).build_recent_weekends_report(3)
    lines = [line for line in text.splitlines() if line[:1].isdigit()]
    assert "Beta" in lines[0]
    assert "Aardvark" in lines[1]
    assert "Alpha" in lines[2]
    assert "Alpha — атак: 5, бонусных: 2, налутал: 450, вложил: 30" in text
    assert "Aardvark — атак: 4, бонусных: 0, налутал: 450, вложил: 0" in text

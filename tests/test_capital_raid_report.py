from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import CapitalRaidParticipant, CapitalRaidWeekend
from app.services.capital_raid_report import CapitalRaidReportService


@pytest.mark.asyncio
async def test_capital_raid_report_when_no_data(session, app_yaml_config):
    text = await CapitalRaidReportService(session, app_yaml_config).build_latest_weekend_report()
    assert text == "⚠️ По клановой столице пока нет сохраненных данных."


@pytest.mark.asyncio
async def test_capital_raid_report_uses_latest_completed_weekend_and_formats_fields(session, app_yaml_config):
    old = CapitalRaidWeekend(clan_tag="#CLAN", raid_season_id="old", state="ended", start_time=datetime(2026, 5, 1, tzinfo=UTC), end_time=datetime(2026, 5, 3, tzinfo=UTC), total_loot=0, total_attacks=0, enemy_districts_destroyed=0, offensive_reward=0, defensive_reward=0, processed_at=datetime(2026, 5, 4, tzinfo=UTC))
    new = CapitalRaidWeekend(clan_tag="#CLAN", raid_season_id="new", state="ended", start_time=datetime(2026, 5, 10, tzinfo=UTC), end_time=datetime(2026, 5, 12, tzinfo=UTC), total_loot=0, total_attacks=0, enemy_districts_destroyed=0, offensive_reward=0, defensive_reward=0, processed_at=datetime(2026, 5, 13, tzinfo=UTC))
    session.add_all([old, new])
    await session.flush()
    session.add_all([
        CapitalRaidParticipant(weekend_id=new.id, player_id=None, player_tag="#A", player_name="PlayerOne", attacks=6, attack_limit=6, bonus_attacks=1, capital_resources_looted=25500, clan_capital_contributions_snapshot=10),
        CapitalRaidParticipant(weekend_id=new.id, player_id=None, player_tag="#B", player_name="PlayerTwo", attacks=5, attack_limit=6, bonus_attacks=0, capital_resources_looted=21900, clan_capital_contributions_snapshot=20),
    ])
    await session.commit()

    text = await CapitalRaidReportService(session, app_yaml_config).build_latest_weekend_report()
    assert "📅 2026-05-10 — 2026-05-12" in text
    assert "1. PlayerOne — атак: 6, бонусных: 1, золото: 25500" in text
    assert "2. PlayerTwo — атак: 5, бонусных: 0, золото: 21900" in text


@pytest.mark.asyncio
async def test_capital_raid_report_sorting_by_loot_attacks_name(session, app_yaml_config):
    weekend = CapitalRaidWeekend(clan_tag="#CLAN", raid_season_id="new", state="ended", start_time=datetime(2026, 5, 10, tzinfo=UTC), end_time=datetime(2026, 5, 12, tzinfo=UTC), total_loot=0, total_attacks=0, enemy_districts_destroyed=0, offensive_reward=0, defensive_reward=0, processed_at=datetime(2026, 5, 13, tzinfo=UTC))
    session.add(weekend)
    await session.flush()
    session.add_all([
        CapitalRaidParticipant(weekend_id=weekend.id, player_id=None, player_tag="#1", player_name="Beta", attacks=5, attack_limit=6, bonus_attacks=0, capital_resources_looted=10000, clan_capital_contributions_snapshot=None),
        CapitalRaidParticipant(weekend_id=weekend.id, player_id=None, player_tag="#2", player_name="Alpha", attacks=5, attack_limit=6, bonus_attacks=0, capital_resources_looted=10000, clan_capital_contributions_snapshot=None),
        CapitalRaidParticipant(weekend_id=weekend.id, player_id=None, player_tag="#3", player_name="Gamma", attacks=6, attack_limit=6, bonus_attacks=0, capital_resources_looted=10000, clan_capital_contributions_snapshot=None),
        CapitalRaidParticipant(weekend_id=weekend.id, player_id=None, player_tag="#4", player_name="Loot", attacks=1, attack_limit=6, bonus_attacks=0, capital_resources_looted=20000, clan_capital_contributions_snapshot=None),
    ])
    await session.commit()

    text = await CapitalRaidReportService(session, app_yaml_config).build_latest_weekend_report()
    lines = [line for line in text.splitlines() if line[:1].isdigit()]
    assert "Loot" in lines[0]
    assert "Gamma" in lines[1]
    assert "Alpha" in lines[2]
    assert "Beta" in lines[3]

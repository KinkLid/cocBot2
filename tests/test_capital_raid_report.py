from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models import CapitalRaidParticipant, CapitalRaidViolation, CapitalRaidWeekend
from app.services.capital_raid_report import CapitalRaidStatsService


def weekend(season: str, start: datetime, end: datetime) -> CapitalRaidWeekend:
    return CapitalRaidWeekend(
        clan_tag="#CLAN",
        raid_season_id=season,
        state="ended",
        start_time=start,
        end_time=end,
        total_loot=0,
        total_attacks=0,
        enemy_districts_destroyed=0,
        offensive_reward=0,
        defensive_reward=0,
        processed_at=end,
    )


@pytest.mark.asyncio
async def test_current_cycle_uses_weekend_end_time_and_includes_whole_weekend(session, app_yaml_config):
    period = SimpleNamespace(
        start=datetime(2026, 5, 21, tzinfo=UTC),
        end=datetime(2026, 6, 21, tzinfo=UTC),
    )
    previous = weekend(
        "previous",
        datetime(2026, 5, 16, tzinfo=UTC),
        datetime(2026, 5, 18, tzinfo=UTC),
    )
    crossing = weekend(
        "crossing",
        datetime(2026, 5, 20, tzinfo=UTC),
        datetime(2026, 5, 23, tzinfo=UTC),
    )
    session.add_all([previous, crossing])
    await session.flush()
    session.add_all(
        [
            CapitalRaidParticipant(
                weekend_id=previous.id, player_tag="#P1", player_name="Player", attacks=6,
                attack_limit=6, bonus_attacks=1, districts_destroyed=9,
                total_destruction_percent=900, capital_resources_looted=999999,
            ),
            CapitalRaidParticipant(
                weekend_id=crossing.id, player_tag="#P1", player_name="Player", attacks=5,
                attack_limit=6, bonus_attacks=0, districts_destroyed=2,
                total_destruction_percent=362, capital_resources_looted=1,
            ),
            CapitalRaidViolation(
                weekend_id=crossing.id, player_tag="#P1", player_name="Player",
                code="capital_under_5_attacks", reason_text="reason", attacks=4,
                detected_at=crossing.end_time,
            ),
        ]
    )
    await session.commit()

    service = CapitalRaidStatsService(session, app_yaml_config)
    rows, stats = await service.build_current_cycle_stats(period)

    assert stats.completed_weekends == 1
    assert rows == [
        {
            "player_tag": "#P1",
            "player_name": "Player",
            "weekends_count": 1,
            "attacks": 5,
            "bonus_attacks": 0,
            "districts_destroyed": 2,
            "total_destruction_percent": 362,
            "capital_violation_count": 1,
        }
    ]
    text = service.format_current_cycle_stats(period, rows, stats)
    assert "🏰 Столица" in text
    assert "📦 Учтено рейдов столицы: 1" in text
    assert "разрушение: 362%" in text


@pytest.mark.asyncio
async def test_current_cycle_stats_empty_message(session, app_yaml_config):
    period = SimpleNamespace(
        start=datetime(2026, 5, 21, tzinfo=UTC),
        end=datetime(2026, 6, 21, tzinfo=UTC),
    )
    service = CapitalRaidStatsService(session, app_yaml_config)
    rows, stats = await service.build_current_cycle_stats(period)
    assert service.format_current_cycle_stats(period, rows, stats) == "⚠️ По столице за текущий цикл пока нет данных."

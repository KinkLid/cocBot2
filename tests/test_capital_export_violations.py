from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import CapitalRaidParticipant, CapitalRaidViolation
from app.services.export import ExportService
from app.services.stats import StatsService
from tests.test_capital_raid_report import weekend
from tests.test_stats import seed_stats_data


async def seed_capital(session, *, attacks: int = 4):
    raid = weekend(
        "20260331:20260402",
        datetime(2026, 3, 31, tzinfo=UTC),
        datetime(2026, 4, 2, 8, tzinfo=UTC),
    )
    session.add(raid)
    await session.flush()
    session.add(
        CapitalRaidParticipant(
            weekend_id=raid.id,
            player_tag="#P2",
            player_name="Alpha",
            attacks=attacks,
            attack_limit=6,
            bonus_attacks=0,
            districts_destroyed=2,
            total_destruction_percent=320,
            capital_resources_looted=999999,
        )
    )
    if attacks < 5:
        session.add(
            CapitalRaidViolation(
                weekend_id=raid.id,
                player_tag="#P2",
                player_name="Alpha",
                code="capital_under_5_attacks",
                reason_text="Игрок сделал меньше 5 атак в рейде столицы",
                attacks=attacks,
                detected_at=raid.end_time,
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_export_contains_capital_participation_and_shared_score(session, app_yaml_config):
    await seed_stats_data(session)
    await seed_capital(session, attacks=4)
    payload = await ExportService(session, app_yaml_config).export_to_dict(
        datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 3, tzinfo=UTC)
    )
    alpha = next(player for player in payload["players"] if player["player_tag"] == "#P2")
    capital = alpha["capital_participation"][0]
    assert capital["raid_season_id"] == "20260331:20260402"
    assert capital["violated"] is True
    assert capital["violation_code"] == "capital_under_5_attacks"
    assert capital["total_destruction_percent"] == 320
    assert capital["dev_capital_score"] == 0.0
    assert all("capital_participation" in player for player in payload["players"])


@pytest.mark.asyncio
async def test_capital_violations_are_in_ranking_and_player_details(session, app_yaml_config):
    await seed_stats_data(session)
    await seed_capital(session, attacks=4)
    service = StatsService(session, app_yaml_config)
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 3, tzinfo=UTC)

    ranking = await service.violations_ranking_current_cycle_data(start, end)
    alpha = next(row for row in ranking if row["player_tag"] == "#P2")
    assert alpha["violations"] >= 1

    report = await service.build_player_violations_report(start, end, "#P2", "Alpha")
    assert "Столица" in report
    assert "capital_under_5_attacks" in report
    assert "Атак в рейде: 4" in report

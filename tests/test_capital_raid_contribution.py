from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models import CapitalRaidParticipant
from app.services.capital_raid_contribution import (
    CapitalRaidContributionService,
    calculate_capital_weekend_score,
)
from tests.test_capital_raid_report import weekend


def test_capital_weekend_score_rules_and_gold_is_irrelevant():
    assert calculate_capital_weekend_score(attacks=4, districts_destroyed=2, total_destruction_percent=320) == 0.0
    assert calculate_capital_weekend_score(attacks=5, districts_destroyed=2, total_destruction_percent=320) == 14.0
    assert calculate_capital_weekend_score(attacks=6, districts_destroyed=3, total_destruction_percent=540) == 19.5


@pytest.mark.asyncio
async def test_contribution_scores_each_weekend_separately(session, app_yaml_config):
    period = SimpleNamespace(
        start=datetime(2026, 5, 21, tzinfo=UTC),
        end=datetime(2026, 6, 21, tzinfo=UTC),
    )
    w1 = weekend("under", datetime(2026, 5, 20, tzinfo=UTC), datetime(2026, 5, 23, tzinfo=UTC))
    w2 = weekend("six", datetime(2026, 5, 29, tzinfo=UTC), datetime(2026, 5, 31, tzinfo=UTC))
    session.add_all([w1, w2])
    await session.flush()
    session.add_all(
        [
            CapitalRaidParticipant(
                weekend_id=w1.id, player_tag="#P1", player_name="Player", attacks=4,
                attack_limit=6, bonus_attacks=0, districts_destroyed=2,
                total_destruction_percent=320, capital_resources_looted=999999999,
            ),
            CapitalRaidParticipant(
                weekend_id=w2.id, player_tag="#P1", player_name="Player", attacks=6,
                attack_limit=6, bonus_attacks=1, districts_destroyed=3,
                total_destruction_percent=540, capital_resources_looted=0,
            ),
        ]
    )
    await session.commit()

    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, stats = await service.build_current_cycle_ranking(period)

    assert stats.completed_weekends == 2
    assert ranking[0]["score"] == 19.5
    assert ranking[0]["violations"] == 1
    assert ranking[0]["attacks"] == 10
    assert "🧪 Dev вклад в столицу" in service.format_current_cycle_ranking(period, ranking, stats)

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

    assert stats.total_completed_weekends == 2
    assert stats.weekends_with_participants == 2
    assert stats.weekends_without_participants == 0
    assert ranking[0]["score"] == 19.5
    assert ranking[0]["violations"] == 1
    assert ranking[0]["attacks"] == 10
    assert "🧪 Dev вклад в столицу" in service.format_current_cycle_ranking(period, ranking, stats)


@pytest.mark.asyncio
async def test_contribution_reports_completed_weekends_without_participant_data(session, app_yaml_config):
    period = SimpleNamespace(
        start=datetime(2026, 5, 21, tzinfo=UTC),
        end=datetime(2026, 6, 21, tzinfo=UTC),
    )
    weekends = [
        weekend(
            f"season-{index}",
            datetime(2026, 5, 22 + index, tzinfo=UTC),
            datetime(2026, 5, 23 + index, tzinfo=UTC),
        )
        for index in range(5)
    ]
    session.add_all(weekends)
    await session.flush()
    session.add(
        CapitalRaidParticipant(
            weekend_id=weekends[0].id, player_tag="#P1", player_name="Player", attacks=6,
            attack_limit=6, bonus_attacks=1, districts_destroyed=3,
            total_destruction_percent=540, capital_resources_looted=0,
        )
    )
    await session.commit()

    service = CapitalRaidContributionService(session, app_yaml_config)
    ranking, stats = await service.build_current_cycle_ranking(period)
    text = service.format_current_cycle_ranking(period, ranking, stats)

    assert stats.total_completed_weekends == 5
    assert stats.weekends_with_participants == 1
    assert stats.weekends_without_participants == 4
    assert ranking[0]["score"] == 19.5
    assert ranking[0]["weekends_count"] == 1
    assert "📦 Завершенных рейдов в цикле: 5" in text
    assert "✅ Рейдов с данными участников: 1" in text
    assert "⚠️ Рейдов без данных участников: 4" in text


@pytest.mark.asyncio
async def test_contribution_empty_cycle_message(session, app_yaml_config):
    period = SimpleNamespace(
        start=datetime(2026, 5, 21, tzinfo=UTC),
        end=datetime(2026, 6, 21, tzinfo=UTC),
    )
    service = CapitalRaidContributionService(session, app_yaml_config)

    ranking, stats = await service.build_current_cycle_ranking(period)

    assert service.format_current_cycle_ranking(period, ranking, stats) == (
        "⚠️ По клановой столице за текущий цикл пока нет данных."
    )


@pytest.mark.asyncio
async def test_contribution_completed_weekends_without_any_participants_message(session, app_yaml_config):
    period = SimpleNamespace(
        start=datetime(2026, 5, 21, tzinfo=UTC),
        end=datetime(2026, 6, 21, tzinfo=UTC),
    )
    session.add(
        weekend("empty", datetime(2026, 5, 22, tzinfo=UTC), datetime(2026, 5, 24, tzinfo=UTC))
    )
    await session.commit()
    service = CapitalRaidContributionService(session, app_yaml_config)

    ranking, stats = await service.build_current_cycle_ranking(period)

    assert stats.total_completed_weekends == 1
    assert stats.weekends_with_participants == 0
    assert stats.weekends_without_participants == 1
    assert service.format_current_cycle_ranking(period, ranking, stats) == (
        "⚠️ В текущем цикле есть завершенные рейды столицы, но по ним нет данных участников."
    )

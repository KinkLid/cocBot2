from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import (
    Attack,
    CapitalRaidViolation,
    CapitalRaidWeekend,
    PlayerAccount,
    Violation,
    ViolationCounterReset,
    War,
)
from app.models.enums import ViolationCode, WarType
from app.repositories.violation_counter_reset import ViolationCounterResetRepository
from app.services.active_violation_counter import ActiveViolationCounterService
from app.services.stats import StatsService
from app.services.dev_contribution import ContributionRankingRow, DevContributionService


async def _seed_violation_history(session, now: datetime):
    player = PlayerAccount(
        player_tag="#P1",
        name="Alpha",
        town_hall=16,
        current_clan_tag="#CLAN",
        current_clan_name="Clan",
        current_clan_rank=1,
        current_in_clan=True,
        last_seen_in_clan_at=now,
        first_absent_at=None,
        created_at=now,
        updated_at=now,
    )
    war = War(
        war_uid="reset-war",
        clan_tag="#CLAN",
        clan_name="Clan",
        opponent_tag="#E",
        opponent_name="Enemy",
        war_type=WarType.REGULAR,
        state="war_ended",
        league_group_id=None,
        cwl_season=None,
        round_index=None,
        team_size=15,
        is_friendly=False,
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=1),
        preparation_start_time=now - timedelta(days=3),
        source_payload={},
    )
    session.add_all([player, war])
    await session.flush()
    attacks = []
    for index in range(4):
        attack = Attack(
            war_id=war.id,
            attacker_player_id=player.id,
            attacker_tag=player.player_tag,
            attacker_name=player.name,
            attacker_position=10,
            attacker_town_hall=16,
            defender_tag=f"#E{index}",
            defender_name=f"Enemy {index}",
            defender_position=5,
            defender_town_hall=16,
            stars=2,
            destruction=80,
            attack_order=index + 1,
            observed_at=now + timedelta(minutes=index),
        )
        session.add(attack)
        attacks.append(attack)
    await session.flush()
    for index, attack in enumerate(attacks):
        session.add(
            Violation(
                attack_id=attack.id,
                war_id=war.id,
                player_tag=player.player_tag,
                code=ViolationCode.ABOVE_SELF,
                reason_text="history",
                player_position=10,
                target_position=5,
                detected_at=now + timedelta(minutes=index),
                is_manual=False,
            )
        )
    weekend = CapitalRaidWeekend(
        clan_tag="#CLAN",
        raid_season_id="reset-weekend",
        state="ended",
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(minutes=4),
        total_loot=0,
        total_attacks=0,
        enemy_districts_destroyed=0,
        offensive_reward=0,
        defensive_reward=0,
        processed_at=now + timedelta(minutes=4),
    )
    session.add(weekend)
    await session.flush()
    session.add(
        CapitalRaidViolation(
            weekend_id=weekend.id,
            player_tag=player.player_tag,
            player_name=player.name,
            code="capital_under_5_attacks",
            reason_text="capital history",
            attacks=4,
            detected_at=now + timedelta(minutes=4),
        )
    )
    await session.commit()
    return player, war


@pytest.mark.asyncio
async def test_reset_marker_restarts_active_counter_without_deleting_history(
    session, app_yaml_config
):
    cycle_start = datetime(2026, 5, 1, tzinfo=UTC)
    cycle_end = datetime(2026, 6, 1, tzinfo=UTC)
    detected_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    player, _ = await _seed_violation_history(session, detected_at)
    counter = ActiveViolationCounterService(session)

    initial_count = await counter.count_for_player(player.player_tag, cycle_start, cycle_end)
    assert initial_count == 5
    formatter = DevContributionService(session, app_yaml_config)
    assert "❌" in formatter.format_contribution_ranking(
        [ContributionRankingRow(player.player_tag, player.name, 1, 100.0, False, initial_count)]
    )

    reset = await ViolationCounterResetRepository(session).add_reset(
        player_tag=player.player_tag,
        cycle_start=cycle_start,
        reset_at=detected_at + timedelta(minutes=4),
        reset_by_admin_telegram_id=1,
    )
    await session.commit()
    assert reset.id is not None
    active_after_reset = await counter.count_for_player(
        player.player_tag, cycle_start, cycle_end
    )
    assert active_after_reset == 0
    assert "❌" not in formatter.format_contribution_ranking(
        [
            ContributionRankingRow(
                player.player_tag, player.name, 1, 100.0, False, active_after_reset
            )
        ]
    )
    reset_options = await StatsService(
        session, app_yaml_config
    ).violation_counter_reset_options(cycle_start, cycle_end)
    assert reset_options == [
        {"player_tag": player.player_tag, "player_name": player.name, "violations": 0}
    ]
    assert await session.scalar(select(func.count(Violation.id))) == 4
    assert await session.scalar(select(func.count(CapitalRaidViolation.id))) == 1


@pytest.mark.asyncio
async def test_new_violation_after_reset_counts_from_one_and_history_report_remains(
    session, app_yaml_config
):
    cycle_start = datetime(2026, 5, 1, tzinfo=UTC)
    cycle_end = datetime(2026, 6, 1, tzinfo=UTC)
    detected_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    player, war = await _seed_violation_history(session, detected_at)
    await ViolationCounterResetRepository(session).add_reset(
        player.player_tag, cycle_start, detected_at + timedelta(minutes=4), 1
    )
    attack = Attack(
        war_id=war.id,
        attacker_player_id=player.id,
        attacker_tag=player.player_tag,
        attacker_name=player.name,
        attacker_position=10,
        attacker_town_hall=16,
        defender_tag="#NEW",
        defender_name="New enemy",
        defender_position=5,
        defender_town_hall=16,
        stars=1,
        destruction=50,
        attack_order=10,
        observed_at=detected_at + timedelta(minutes=5),
    )
    session.add(attack)
    await session.flush()
    session.add(
        Violation(
            attack_id=attack.id,
            war_id=war.id,
            player_tag=player.player_tag,
            code=ViolationCode.ABOVE_SELF,
            reason_text="new",
            player_position=10,
            target_position=5,
            detected_at=attack.observed_at,
            is_manual=False,
        )
    )
    await session.commit()

    service = StatsService(session, app_yaml_config)
    ranking = await service.violations_ranking_current_cycle_data(cycle_start, cycle_end)
    report = await service.build_player_violations_report(
        cycle_start, cycle_end, player.player_tag, player.name
    )

    assert ranking == [
        {"player_tag": player.player_tag, "player_name": player.name, "violations": 1}
    ]
    assert "Активный счетчик нарушений: 1" in report
    assert "capital history" in report
    assert "Причина: history" in report
    assert "Причина: new" in report
    assert await session.scalar(select(func.count(ViolationCounterReset.id))) == 1


@pytest.mark.asyncio
async def test_war_notification_number_restarts_after_reset(
    session, fake_clash_client, app_yaml_config
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services.war_sync import WarSyncService

    cycle_start = datetime(2026, 5, 1, tzinfo=UTC)
    cycle_end = datetime(2026, 6, 1, tzinfo=UTC)
    reset_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    war = War(
        war_uid="notification-reset-war",
        clan_tag="#CLAN",
        clan_name="Clan",
        opponent_tag="#E",
        opponent_name="Enemy",
        war_type=WarType.REGULAR,
        state="in_war",
        league_group_id=None,
        cwl_season=None,
        round_index=None,
        team_size=15,
        is_friendly=False,
        start_time=reset_at - timedelta(hours=1),
        end_time=reset_at + timedelta(hours=5),
        preparation_start_time=reset_at - timedelta(days=1),
        source_payload={},
    )
    session.add(war)
    await session.flush()
    attack = Attack(
        war_id=war.id,
        attacker_player_id=None,
        attacker_tag="#P1",
        attacker_name="Alpha",
        attacker_position=10,
        attacker_town_hall=16,
        defender_tag="#E1",
        defender_name="Enemy",
        defender_position=8,
        defender_town_hall=16,
        stars=2,
        destruction=80,
        attack_order=1,
        observed_at=reset_at + timedelta(minutes=1),
    )
    session.add(attack)
    await session.flush()
    await ViolationCounterResetRepository(session).add_reset(
        attack.attacker_tag, cycle_start, reset_at, 1
    )
    notifier = SimpleNamespace(notify_once=AsyncMock())
    service = WarSyncService(session, fake_clash_client, app_yaml_config, notifier)
    service.period_service.current_cycle = AsyncMock(
        return_value=SimpleNamespace(start=cycle_start, end=cycle_end)
    )

    await service._reconcile_violation(war, attack)

    notification_text = notifier.notify_once.await_args.kwargs["text"]
    assert "Нарушение №1" in notification_text

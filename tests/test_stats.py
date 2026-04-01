from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Attack, CycleBoundary, PlayerAccount, TelegramPlayerLink, TelegramUser, Violation, War, WarParticipant
from app.models.enums import ViolationCode, WarState, WarType
from app.services.period import PeriodService
from app.services.stats import StatsService


async def seed_stats_data(session) -> None:
    session.add_all(
        [
            CycleBoundary(source_key="cwl:2026-03", boundary_at=datetime(2026, 3, 6, tzinfo=UTC), description="b1"),
            CycleBoundary(source_key="cwl:2026-04", boundary_at=datetime(2026, 4, 4, tzinfo=UTC), description="b2"),
        ]
    )
    tg = TelegramUser(telegram_id=100, username="tester", registered_at=datetime(2026, 1, 28, 1, 36, tzinfo=UTC))
    session.add(tg)
    await session.flush()
    p1 = PlayerAccount(
        player_tag="#P2",
        name="Alpha",
        town_hall=16,
        current_clan_tag="#CLAN",
        current_clan_name="TestClan",
        current_clan_rank=2,
        current_in_clan=True,
        last_seen_in_clan_at=datetime(2026, 4, 1, tzinfo=UTC),
        first_absent_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    p2 = PlayerAccount(
        player_tag="#P8",
        name="Bravo",
        town_hall=15,
        current_clan_tag="#CLAN",
        current_clan_name="TestClan",
        current_clan_rank=1,
        current_in_clan=True,
        last_seen_in_clan_at=datetime(2026, 4, 1, tzinfo=UTC),
        first_absent_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    p3 = PlayerAccount(
        player_tag="#P9",
        name="Ghost",
        town_hall=16,
        current_clan_tag=None,
        current_clan_name=None,
        current_clan_rank=None,
        current_in_clan=False,
        last_seen_in_clan_at=datetime(2026, 3, 20, tzinfo=UTC),
        first_absent_at=datetime(2026, 3, 21, tzinfo=UTC),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add_all([p1, p2, p3])
    await session.flush()
    session.add(TelegramPlayerLink(telegram_user_id=tg.id, player_tag="#P2", linked_at=datetime(2026, 1, 28, 1, 36, tzinfo=UTC)))

    war_prev = War(
        war_uid="prev",
        clan_tag="#CLAN",
        clan_name="TestClan",
        opponent_tag="#E2",
        opponent_name="Enemy",
        war_type=WarType.REGULAR,
        state=WarState.WAR_ENDED,
        league_group_id=None,
        cwl_season=None,
        round_index=None,
        team_size=15,
        is_friendly=False,
        start_time=datetime(2026, 3, 10, 12, tzinfo=UTC),
        end_time=datetime(2026, 3, 11, 12, tzinfo=UTC),
        preparation_start_time=datetime(2026, 3, 9, 12, tzinfo=UTC),
        source_payload={},
    )
    war_curr = War(
        war_uid="curr",
        clan_tag="#CLAN",
        clan_name="TestClan",
        opponent_tag="#E8",
        opponent_name="Enemy2",
        war_type=WarType.CWL,
        state=WarState.WAR_ENDED,
        league_group_id="#CLAN:2026-04",
        cwl_season="2026-04",
        round_index=1,
        team_size=15,
        is_friendly=False,
        start_time=datetime(2026, 4, 1, 12, tzinfo=UTC),
        end_time=datetime(2026, 4, 2, 12, tzinfo=UTC),
        preparation_start_time=datetime(2026, 3, 31, 12, tzinfo=UTC),
        source_payload={},
    )
    session.add_all([war_prev, war_curr])
    await session.flush()
    session.add_all(
        [
            WarParticipant(war_id=war_prev.id, player_id=p1.id, player_tag="#P2", name="Alpha", map_position=2, town_hall=16, is_own_clan=True),
            WarParticipant(war_id=war_prev.id, player_id=p2.id, player_tag="#P8", name="Bravo", map_position=1, town_hall=15, is_own_clan=True),
            WarParticipant(war_id=war_curr.id, player_id=p1.id, player_tag="#P2", name="Alpha", map_position=2, town_hall=16, is_own_clan=True),
            WarParticipant(war_id=war_curr.id, player_id=p2.id, player_tag="#P8", name="Bravo", map_position=1, town_hall=15, is_own_clan=True),
        ]
    )
    await session.flush()
    attack1 = Attack(
        war_id=war_prev.id,
        attacker_player_id=p1.id,
        attacker_tag="#P2",
        attacker_name="Alpha",
        attacker_position=2,
        attacker_town_hall=16,
        defender_tag="#E2",
        defender_name="Enemy2",
        defender_position=2,
        defender_town_hall=16,
        stars=2,
        destruction=80.0,
        attack_order=1,
        observed_at=datetime(2026, 3, 10, 13, tzinfo=UTC),
    )
    attack2 = Attack(
        war_id=war_curr.id,
        attacker_player_id=p1.id,
        attacker_tag="#P2",
        attacker_name="Alpha",
        attacker_position=2,
        attacker_town_hall=16,
        defender_tag="#E8",
        defender_name="Enemy8",
        defender_position=2,
        defender_town_hall=16,
        stars=3,
        destruction=100.0,
        attack_order=2,
        observed_at=datetime(2026, 4, 1, 14, tzinfo=UTC),
    )
    attack3 = Attack(
        war_id=war_curr.id,
        attacker_player_id=p2.id,
        attacker_tag="#P8",
        attacker_name="Bravo",
        attacker_position=1,
        attacker_town_hall=15,
        defender_tag="#E9",
        defender_name="Enemy9",
        defender_position=1,
        defender_town_hall=16,
        stars=1,
        destruction=50.0,
        attack_order=3,
        observed_at=datetime(2026, 4, 1, 15, tzinfo=UTC),
    )
    session.add_all([attack1, attack2, attack3])
    await session.flush()
    session.add(Violation(attack_id=attack3.id, war_id=war_curr.id, player_tag="#P8", code=ViolationCode.ABOVE_SELF, reason_text="test", player_position=1, target_position=1, detected_at=datetime(2026, 4, 1, 15, tzinfo=UTC)))
    await session.commit()


@pytest.mark.asyncio
async def test_stats_for_current_cycle(session, app_yaml_config):
    await seed_stats_data(session)
    period = await PeriodService(session).current_cycle(datetime(2026, 4, 1, 18, tzinfo=UTC))
    stats = await StatsService(session, app_yaml_config).clan_stats(period.start, period.end)
    assert "#P2" in stats.text
    assert "⭐ Звёзд: 5" in stats.text


@pytest.mark.asyncio
async def test_stats_for_previous_cycle(session, app_yaml_config):
    await seed_stats_data(session)
    period = await PeriodService(session).previous_cycle(datetime(2026, 4, 5, 0, tzinfo=UTC))
    stats = await StatsService(session, app_yaml_config).clan_stats(period.start, period.end)
    assert "#P2" in stats.text
    assert "⭐ Звёзд: 5" in stats.text


@pytest.mark.asyncio
async def test_stats_for_custom_period(session, app_yaml_config):
    await seed_stats_data(session)
    stats = await StatsService(session, app_yaml_config).clan_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC))
    assert "#P8" in stats.text
    assert "⚠️ Нарушений: 1" in stats.text


@pytest.mark.asyncio
async def test_only_current_clan_members_are_included_in_stats(session, app_yaml_config):
    await seed_stats_data(session)
    stats = await StatsService(session, app_yaml_config).clan_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC))
    assert "#P9" not in stats.text


@pytest.mark.asyncio
async def test_player_place_in_clan_is_calculated_by_stars(session, app_yaml_config):
    await seed_stats_data(session)
    stats = await StatsService(session, app_yaml_config).clan_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC), sort_by="stars")
    assert stats.rows[0].player_tag == "#P2"
    assert stats.rows[0].place == 1
    assert stats.rows[1].player_tag == "#P8"
    assert stats.rows[1].place == 2


@pytest.mark.asyncio
async def test_admin_list_default_sort_uses_current_clan_order(session, app_yaml_config):
    await seed_stats_data(session)
    stats = await StatsService(session, app_yaml_config).clan_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC))
    assert [row.player_tag for row in stats.rows] == ["#P8", "#P2"]

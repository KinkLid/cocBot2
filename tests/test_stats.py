from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Attack, CycleBoundary, PlayerAccount, TelegramPlayerLink, TelegramUser, Violation, War, WarParticipant
from app.models.enums import ViolationCode, WarState, WarType
from app.services.period import PeriodService
from app.services.stats import StatsService
from app.services.dev_contribution import ContributionDataUnavailableError, ContributionRankingRow


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
async def test_previous_cycle_raises_clear_error_with_insufficient_boundaries(session):
    with pytest.raises(ValueError, match="Прошлый цикл недоступен: в базе недостаточно границ циклов ЛВК"):
        await PeriodService(session).previous_cycle(datetime(2026, 4, 5, 0, tzinfo=UTC))
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
async def test_players_list_sort_by_stars_is_unchanged(session, app_yaml_config):
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


@pytest.mark.asyncio
async def test_player_stats_place_uses_contribution_not_stars(session, app_yaml_config, monkeypatch):
    await seed_stats_data(session)

    async def fake_ranking(*_args, **_kwargs):
        return [
            ContributionRankingRow(player_tag="#P8", player_name="Bravo", wars=1, score=50.0, newcomer=False),
            ContributionRankingRow(player_tag="#P2", player_name="Alpha", wars=1, score=10.0, newcomer=False),
        ]

    monkeypatch.setattr("app.services.dev_contribution.DevContributionService.build_contribution_ranking", fake_ranking)

    stats = await StatsService(session, app_yaml_config).player_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC), "#P8")
    assert stats.place == 1


@pytest.mark.asyncio
async def test_player_stats_place_matches_contribution_ranking(session, app_yaml_config, monkeypatch):
    await seed_stats_data(session)

    async def fake_ranking(*_args, **_kwargs):
        return [
            ContributionRankingRow(player_tag="#P8", player_name="Bravo", wars=1, score=50.0, newcomer=False),
            ContributionRankingRow(player_tag="#P2", player_name="Alpha", wars=1, score=10.0, newcomer=False),
        ]

    monkeypatch.setattr("app.services.dev_contribution.DevContributionService.build_contribution_ranking", fake_ranking)

    service = StatsService(session, app_yaml_config)
    p8 = await service.player_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC), "#P8")
    p2 = await service.player_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC), "#P2")
    assert (p8.place, p2.place) == (1, 2)


@pytest.mark.asyncio
async def test_player_stats_handles_missing_contribution_data(session, app_yaml_config, monkeypatch):
    await seed_stats_data(session)


@pytest.mark.asyncio
async def test_violations_ranking_current_cycle_basic(session, app_yaml_config):
    await seed_stats_data(session)
    service = StatsService(session, app_yaml_config)
    text = await service.violations_ranking_current_cycle(
        datetime(2026, 4, 1, 0, tzinfo=UTC),
        datetime(2026, 4, 2, 23, tzinfo=UTC),
    )
    assert "🚨 Нарушения за текущий цикл" in text
    assert "1. Bravo — 1" in text
    assert "Alpha" not in text
    assert "Ghost" not in text


@pytest.mark.asyncio
async def test_violations_ranking_current_cycle_tie_breaker(session, app_yaml_config):
    await seed_stats_data(session)
    p4 = PlayerAccount(
        player_tag="#P10",
        name="Charlie",
        town_hall=16,
        current_clan_tag="#CLAN",
        current_clan_name="TestClan",
        current_clan_rank=3,
        current_in_clan=True,
        last_seen_in_clan_at=datetime(2026, 4, 1, tzinfo=UTC),
        first_absent_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(p4)
    await session.flush()
    session.add(
        Violation(
            attack_id=None,
            war_id=None,
            player_tag="#P10",
            code=ViolationCode.TOO_LOW,
            reason_text="tie",
            player_position=3,
            target_position=10,
            detected_at=datetime(2026, 4, 1, 16, tzinfo=UTC),
        )
    )
    await session.commit()

    service = StatsService(session, app_yaml_config)
    text = await service.violations_ranking_current_cycle(
        datetime(2026, 4, 1, 0, tzinfo=UTC),
        datetime(2026, 4, 2, 23, tzinfo=UTC),
    )
    lines = [line for line in text.splitlines() if line and line[0].isdigit()]
    assert lines[0].endswith("Bravo — 1")
    assert lines[1].endswith("Charlie — 1")


@pytest.mark.asyncio
async def test_violations_ranking_current_cycle_empty(session, app_yaml_config):
    await seed_stats_data(session)
    service = StatsService(session, app_yaml_config)
    text = await service.violations_ranking_current_cycle(
        datetime(2026, 3, 1, 0, tzinfo=UTC),
        datetime(2026, 3, 2, 23, tzinfo=UTC),
    )
    assert text == "✅ За текущий цикл нарушений пока нет."

    async def fail_ranking(*_args, **_kwargs):
        raise ContributionDataUnavailableError("no data")

    monkeypatch.setattr("app.services.dev_contribution.DevContributionService.build_contribution_ranking", fail_ranking)

    stats = await StatsService(session, app_yaml_config).player_stats(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC), "#P2")
    assert stats.place == 0

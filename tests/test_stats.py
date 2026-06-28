from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Attack, CycleBoundary, PlayerAccount, TelegramPlayerLink, TelegramUser, Violation, ViolationCounterReset, War, WarParticipant
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
    assert "⚠️ Активных нарушений: 1" in stats.text


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
    assert "1. Bravo — всего: 1, активных: 1" in text
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
    war = await session.scalar(select(War).where(War.war_type == WarType.REGULAR))
    attack = Attack(
        war_id=war.id,
        attacker_player_id=p4.id,
        attacker_tag="#P10",
        attacker_name="Charlie",
        attacker_position=3,
        attacker_town_hall=16,
        defender_tag="#E10",
        defender_name="Enemy10",
        defender_position=10,
        defender_town_hall=16,
        stars=1,
        destruction=50,
        attack_order=99,
        observed_at=datetime(2026, 4, 1, 16, tzinfo=UTC),
    )
    session.add(attack)
    await session.flush()
    session.add(
        Violation(
            attack_id=attack.id,
            war_id=war.id,
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
    assert "Bravo — всего: 1, активных: 1" in lines[0]
    assert "Charlie — всего: 1, активных: 1" in lines[1]


@pytest.mark.asyncio
async def test_violations_ranking_current_cycle_tie_breaker_uses_active_count(session, app_yaml_config):
    await seed_stats_data(session)
    p4 = PlayerAccount(
        player_tag="#P10", name="Charlie", town_hall=16, current_clan_tag="#CLAN",
        current_clan_name="TestClan", current_clan_rank=3, current_in_clan=True,
        last_seen_in_clan_at=datetime(2026, 4, 1, tzinfo=UTC), created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    session.add(p4)
    await session.flush()
    war = await session.scalar(select(War).where(War.war_type == WarType.REGULAR))
    for order, detected_at in [(90, datetime(2026, 4, 1, 16, tzinfo=UTC)), (91, datetime(2026, 4, 1, 17, tzinfo=UTC))]:
        attack = Attack(war_id=war.id, attacker_player_id=p4.id, attacker_tag="#P10", attacker_name="Charlie", attacker_position=3, attacker_town_hall=16, defender_tag=f"#E{order}", defender_name="Enemy", defender_position=10, defender_town_hall=16, stars=1, destruction=50, attack_order=order, observed_at=detected_at)
        session.add(attack)
        await session.flush()
        session.add(Violation(attack_id=attack.id, war_id=war.id, player_tag="#P10", code=ViolationCode.TOO_LOW, reason_text="tie", player_position=3, target_position=10, detected_at=detected_at))
    session.add(ViolationCounterReset(player_tag="#P10", cycle_start=datetime(2026, 4, 1, 0, tzinfo=UTC), reset_at=datetime(2026, 4, 1, 18, tzinfo=UTC), reset_by_admin_telegram_id=1, reset_amount=1))
    await session.commit()

    rows = await StatsService(session, app_yaml_config).violations_ranking_current_cycle_data(
        datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC)
    )

    assert [(row["player_name"], row["violations"], row["active_violations"]) for row in rows[:2]] == [
        ("Charlie", 2, 1),
        ("Bravo", 1, 1),
    ]


@pytest.mark.asyncio
async def test_violations_ranking_current_cycle_empty(session, app_yaml_config):
    await seed_stats_data(session)
    service = StatsService(session, app_yaml_config)
    text = await service.violations_ranking_current_cycle(
        datetime(2026, 3, 1, 0, tzinfo=UTC),
        datetime(2026, 3, 2, 23, tzinfo=UTC),
    )
    assert text == "✅ За текущий цикл нарушений пока нет."



@pytest.mark.asyncio
async def test_player_stats_returns_zero_place_when_contribution_unavailable(session, app_yaml_config, monkeypatch):
    await seed_stats_data(session)

    async def fail_ranking(*_args, **_kwargs):
        raise ContributionDataUnavailableError("no data")

    monkeypatch.setattr("app.services.dev_contribution.DevContributionService.build_contribution_ranking", fail_ranking)

    stats = await StatsService(session, app_yaml_config).player_stats(
        datetime(2026, 4, 1, 0, tzinfo=UTC),
        datetime(2026, 4, 2, 23, tzinfo=UTC),
        "#P2",
    )
    assert stats.place == 0


@pytest.mark.asyncio
async def test_build_player_violations_report_empty(session, app_yaml_config, monkeypatch):
    service = StatsService(session, app_yaml_config)

    async def fake_list(*_args, **_kwargs):
        return []

    monkeypatch.setattr(service.war_repo, "list_player_violations_in_period", fake_list)
    text = await service.build_player_violations_report(
        datetime(2026, 4, 1, 0, tzinfo=UTC),
        datetime(2026, 4, 2, 23, tzinfo=UTC),
        "#P1",
        "Lester",
    )
    assert text == "✅ У игрока Lester нет нарушений за текущий цикл.\nАктивный счетчик нарушений: 0"


@pytest.mark.asyncio
async def test_build_player_violations_report_formats_details_and_claimed_target(session, app_yaml_config, monkeypatch):
    from types import SimpleNamespace
    from app.models.enums import WarType, ViolationCode

    service = StatsService(session, app_yaml_config)

    async def fake_list(*_args, **_kwargs):
        return [
            (
                SimpleNamespace(detected_at=datetime(2026, 5, 14, 8, 18, tzinfo=UTC), code=ViolationCode.ABOVE_SELF, reason_text="Атака выше"),
                SimpleNamespace(attacker_position=10, defender_position=8),
                SimpleNamespace(war_type=WarType.REGULAR),
            ),
            (
                SimpleNamespace(detected_at=datetime(2026, 5, 16, 9, 52, tzinfo=UTC), code=ViolationCode.CLAIMED_TARGET, reason_text="Атака по чужому флажку"),
                SimpleNamespace(attacker_position=10, defender_position=23),
                SimpleNamespace(war_type=WarType.CWL),
            ),
        ]

    monkeypatch.setattr(service.war_repo, "list_player_violations_in_period", fake_list)
    text = await service.build_player_violations_report(
        datetime(2026, 4, 1, 0, tzinfo=UTC),
        datetime(2026, 4, 2, 23, tzinfo=UTC),
        "#P1",
        "Lester",
    )
    assert "2026-05-14 08:18 | КВ | 10 -> 8" in text
    assert "2026-05-16 09:52 | ЛВК | 10 -> 23" in text
    assert "Код: claimed_target" in text
    assert "Причина: Атака по чужому флажку" in text


def _player(tag, name, rank=1, in_clan=True):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return PlayerAccount(player_tag=tag, name=name, town_hall=16, current_clan_tag="#CLAN" if in_clan else None, current_clan_name="Clan" if in_clan else None, current_clan_rank=rank, current_in_clan=in_clan, last_seen_in_clan_at=now, first_absent_at=None if in_clan else now, created_at=now, updated_at=now)


def _war(uid, clan="#CLAN", when=datetime(2026, 4, 1, 12, tzinfo=UTC), war_type=WarType.REGULAR):
    return War(war_uid=uid, clan_tag=clan, clan_name="Clan", opponent_tag="#E", opponent_name="Enemy", war_type=war_type, state=WarState.WAR_ENDED, league_group_id=None, cwl_season=None, round_index=None, team_size=15, is_friendly=False, start_time=when, end_time=when, preparation_start_time=when, source_payload={})


async def _add_war_violation(session, player, war, when, code=ViolationCode.TOO_LOW, attack=True, reason="reason"):
    session.add(war)
    await session.flush()
    attack_obj = None
    if attack:
        attack_obj = Attack(war_id=war.id, attacker_player_id=player.id, attacker_tag=player.player_tag, attacker_name=player.name, attacker_position=5, attacker_town_hall=16, defender_tag="#E1", defender_name="Enemy", defender_position=8, defender_town_hall=16, stars=1, destruction=50, attack_order=1, observed_at=when)
        session.add(attack_obj)
        await session.flush()
    violation = Violation(attack_id=attack_obj.id if attack_obj else None, war_id=war.id, player_tag=player.player_tag, code=code, reason_text=reason, player_position=5, target_position=8, detected_at=when)
    session.add(violation)
    await session.flush()
    return violation


async def _add_capital_violation(session, player, when, clan="#CLAN", end_time_marker="use"):
    from app.models import CapitalRaidViolation, CapitalRaidWeekend
    end_time = when if end_time_marker == "use" else None
    weekend = CapitalRaidWeekend(clan_tag=clan, raid_season_id=f"raid-{player.player_tag}-{when.timestamp()}-{clan}", state="ended", start_time=when, end_time=end_time, total_loot=0, total_attacks=0, enemy_districts_destroyed=0, offensive_reward=0, defensive_reward=0, processed_at=when)
    session.add(weekend)
    await session.flush()
    violation = CapitalRaidViolation(weekend_id=weekend.id, player_tag=player.player_tag, player_name=player.name, code="capital_missed_attacks", reason_text="capital reason", attacks=1, detected_at=when)
    session.add(violation)
    await session.flush()
    return violation


@pytest.mark.asyncio
async def test_all_time_violations_include_all_cycles(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("w1", when=datetime(2026, 3, 1, tzinfo=UTC)), datetime(2026, 3, 1, tzinfo=UTC))
    await _add_war_violation(session, p, _war("w2", when=datetime(2026, 4, 1, tzinfo=UTC)), datetime(2026, 4, 1, tzinfo=UTC))
    await session.commit()
    rows = await StatsService(session, app_yaml_config).all_time_violations_data()
    assert rows[0]["violations"] == 2


@pytest.mark.asyncio
async def test_all_time_violations_include_war_capital_and_cwl_miss(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("w1"), datetime(2026, 4, 1, tzinfo=UTC))
    await _add_war_violation(session, p, _war("w2", war_type=WarType.CWL), datetime(2026, 4, 2, tzinfo=UTC), code=ViolationCode.CWL_MISSED_ATTACK, attack=False, reason="Не использовал атаку в ЛВК")
    await _add_capital_violation(session, p, datetime(2026, 4, 3, tzinfo=UTC))
    await session.commit()
    rows = await StatsService(session, app_yaml_config).all_time_violations_data()
    assert rows[0]["violations"] == 3


@pytest.mark.asyncio
async def test_all_time_violations_include_former_clan_member(session, app_yaml_config):
    p = _player("#P1", "Alpha", in_clan=False)
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("w1"), datetime(2026, 4, 1, tzinfo=UTC))
    await session.commit()
    service = StatsService(session, app_yaml_config)
    rows = await service.all_time_violations_data()
    text = await service.all_time_violations()
    assert rows[0]["current_in_clan"] is False
    assert "вышел из клана" in text


@pytest.mark.asyncio
async def test_all_time_violations_exclude_players_without_violations(session, app_yaml_config):
    session.add(_player("#P1", "Alpha")); await session.commit()
    assert await StatsService(session, app_yaml_config).all_time_violations_data() == []


@pytest.mark.asyncio
async def test_all_time_violations_exclude_other_clan_records(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("w1", clan="#OTHER"), datetime(2026, 4, 1, tzinfo=UTC))
    await _add_capital_violation(session, p, datetime(2026, 4, 2, tzinfo=UTC), clan="#OTHER")
    await session.commit()
    assert await StatsService(session, app_yaml_config).all_time_violations_data() == []


@pytest.mark.asyncio
async def test_all_time_violations_ignore_counter_resets(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    for i in range(3):
        await _add_war_violation(session, p, _war(f"w{i}"), datetime(2026, 4, i + 1, tzinfo=UTC))
    session.add(ViolationCounterReset(player_tag="#P1", cycle_start=datetime(2026, 4, 1, tzinfo=UTC), reset_at=datetime(2026, 4, 4, tzinfo=UTC), reset_by_admin_telegram_id=1, reset_amount=None))
    session.add(ViolationCounterReset(player_tag="#P1", cycle_start=datetime(2026, 4, 1, tzinfo=UTC), reset_at=datetime(2026, 4, 5, tzinfo=UTC), reset_by_admin_telegram_id=1, reset_amount=2))
    await session.commit()
    assert (await StatsService(session, app_yaml_config).all_time_violations_data())[0]["violations"] == 3


@pytest.mark.asyncio
async def test_all_time_violations_ranking_order(session, app_yaml_config):
    players = [_player("#P1", "Alpha", 3), _player("#P2", "Bravo", 1, False), _player("#P3", "Charlie", 2), _player("#P4", "Delta", 1)]
    session.add_all(players); await session.flush()
    for i in range(2):
        await _add_war_violation(session, players[3], _war(f"wd{i}"), datetime(2026, 4, i + 1, tzinfo=UTC))
    for idx, p in enumerate(players[:3]):
        await _add_war_violation(session, p, _war(f"w{idx}"), datetime(2026, 5, idx + 1, tzinfo=UTC))
    await session.commit()
    names = [row["player_name"] for row in await StatsService(session, app_yaml_config).all_time_violations_data()]
    assert names == ["Delta", "Charlie", "Alpha", "Bravo"]


@pytest.mark.asyncio
async def test_build_player_all_time_report_contains_every_violation(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("w1"), datetime(2026, 3, 1, 20, tzinfo=UTC), reason="war reason")
    await _add_war_violation(session, p, _war("w2", war_type=WarType.CWL), datetime(2026, 4, 1, 20, tzinfo=UTC), code=ViolationCode.CWL_MISSED_ATTACK, attack=False, reason="Не использовал атаку в ЛВК")
    await _add_capital_violation(session, p, datetime(2026, 4, 2, 20, tzinfo=UTC))
    await session.commit()
    text = await StatsService(session, app_yaml_config).build_player_all_time_violations_report(player_tag="#P1", player_name="Alpha")
    assert "🗄 Все нарушения игрока: Alpha" in text
    assert "Тег: #P1" in text
    assert "Всего нарушений в базе: 3" in text
    assert "war reason" in text and "ЛВК | пропуск атаки" in text and "Столица" in text


@pytest.mark.asyncio
async def test_build_player_all_time_report_is_chronological(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("late"), datetime(2026, 4, 3, tzinfo=UTC), reason="late")
    await _add_war_violation(session, p, _war("early"), datetime(2026, 4, 1, tzinfo=UTC), reason="early")
    await session.commit()
    text = await StatsService(session, app_yaml_config).build_player_all_time_violations_report(player_tag="#P1", player_name="Alpha")
    assert text.index("early") < text.index("late")


@pytest.mark.asyncio
async def test_build_player_all_time_report_formats_cwl_missed_attack(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("cwl", war_type=WarType.CWL), datetime(2026, 4, 1, 20, tzinfo=UTC), code=ViolationCode.CWL_MISSED_ATTACK, attack=False, reason="Не использовал атаку в ЛВК")
    await session.commit()
    text = await StatsService(session, app_yaml_config).build_player_all_time_violations_report(player_tag="#P1", player_name="Alpha")
    assert "ЛВК | пропуск атаки" in text
    assert "Код: cwl_missed_attack" in text
    assert "Причина: Не использовал атаку в ЛВК" in text


@pytest.mark.asyncio
async def test_build_player_all_time_report_handles_capital_without_end_time(session, app_yaml_config):
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_capital_violation(session, p, datetime(2026, 4, 2, 20, tzinfo=UTC), end_time_marker="none")
    await session.commit()
    text = await StatsService(session, app_yaml_config).build_player_all_time_violations_report(player_tag="#P1", player_name="Alpha")
    assert "Столица" in text


@pytest.mark.asyncio
async def test_build_player_all_time_report_does_not_use_active_counter(session, app_yaml_config, monkeypatch):
    from app.services.active_violation_counter import ActiveViolationCounterService
    p = _player("#P1", "Alpha")
    session.add(p); await session.flush()
    await _add_war_violation(session, p, _war("w1"), datetime(2026, 4, 1, tzinfo=UTC))
    await session.commit()
    async def fail(*args, **kwargs):
        raise AssertionError("active counter must not be used")
    monkeypatch.setattr(ActiveViolationCounterService, "count_for_player", fail)
    monkeypatch.setattr(ActiveViolationCounterService, "counts_for_players", fail)
    text = await StatsService(session, app_yaml_config).build_player_all_time_violations_report(player_tag="#P1", player_name="Alpha")
    assert "Всего нарушений в базе: 1" in text


@pytest.mark.asyncio
async def test_current_cycle_violation_report_is_unchanged(session, app_yaml_config):
    await seed_stats_data(session)
    text = await StatsService(session, app_yaml_config).build_player_violations_report(datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC), "#P8", "Bravo")
    assert "🚨 Нарушения игрока" in text
    assert "Всего нарушений за цикл" in text
    assert "Активный счетчик нарушений" in text

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base

from app.bot.handlers.admin import (
    dev_contribution,
    dev_donations,
    previous_cycle_contribution,
)
from app.bot.keyboards.main import main_menu
from app.domain.dev_contribution import (
    ContributionAttackInput,
    calculate_attack_contribution,
    calculate_cwl_unused_attack_penalty,
    calculate_unused_attack_penalty,
)
from app.models import Attack, ClanMembershipHistory, PlayerAccount, War
from app.models.enums import ViolationCode, WarState, WarType
from app.schemas.dto import PlayerProfileDTO
from app.services import dev_contribution as contribution_module
from app.services.contribution_breakdown import (
    ContributionBreakdownItem,
    ContributionBreakdownService,
    PlayerContributionBreakdown,
)
from app.services.dev_contribution import (
    ContributionDataUnavailableError,
    ContributionRankingRow,
    DevContributionService,
)
from app.services.auth import AuthService
from app.services.active_violation_counter import ActiveViolationCounterService
from app.services.donations import DonationService
from tests.fakes import FakeMessage


NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _default_active_violation_counts(monkeypatch):
    monkeypatch.setattr(
        ActiveViolationCounterService,
        "counts_for_players",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        DonationService,
        "calculate_player_donations_for_period",
        AsyncMock(return_value=0),
    )



def test_contribution_formulas():
    assert calculate_attack_contribution(ContributionAttackInput(stars=2, destruction=80, attacker_position=1, defender_position=1, is_cwl=False)).score == 28
    assert calculate_attack_contribution(ContributionAttackInput(stars=2, destruction=80, attacker_position=1, defender_position=1, is_cwl=False, is_above_self_violation=True)).score == 0
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=1, defender_position=1, is_cwl=False, is_above_self_violation=True)).score == 40
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=1, defender_position=20, is_cwl=False, is_too_low_violation=True)).score < 0
    assert calculate_attack_contribution(ContributionAttackInput(stars=1, destruction=30, attacker_position=1, defender_position=20, is_cwl=False, is_too_low_violation=True)).score == -40
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=1, defender_position=20, is_cwl=True, is_too_low_violation=True, is_above_self_violation=True)).score == 65.0




def test_above_self_non_triple_is_zero():
    assert calculate_attack_contribution(ContributionAttackInput(stars=2, destruction=99, attacker_position=7, defender_position=6, is_cwl=False, is_above_self_violation=True)).score == 0


def test_above_self_triple_uses_base_without_bonus():
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=7, defender_position=6, is_cwl=False, is_above_self_violation=True)).score == 40


def test_regular_triple_without_violation_keeps_bonus():
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=7, defender_position=7, is_cwl=False)).score == 48


def test_too_low_still_applies_when_not_above_self():
    assert calculate_attack_contribution(ContributionAttackInput(stars=2, destruction=80, attacker_position=1, defender_position=20, is_cwl=False, is_too_low_violation=True)).score < 0


def test_cwl_still_ignores_positional_penalties():
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=1, defender_position=20, is_cwl=True, is_too_low_violation=True, is_above_self_violation=True)).score == 65.0


def _build_contribution_calculation_for_attack(
    app_yaml_config,
    monkeypatch,
    *,
    target: int,
    stored_violation,
    attacker_position: int = 3,
    war_type: WarType = WarType.REGULAR,
):
    period = SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)
    player = SimpleNamespace(
        player_tag="#DARK",
        player_name="THE_DARK_KING",
        wars=1,
        player_id=1,
    )
    war = SimpleNamespace(
        id=100 + target,
        war_type=war_type,
        start_time=NOW - timedelta(hours=2),
        end_time=NOW - timedelta(minutes=1),
    )
    attack = SimpleNamespace(
        attacker_tag="#DARK",
        stars=3,
        destruction=100,
        attacker_position=attacker_position,
        defender_position=target,
        observed_at=NOW,
    )
    monkeypatch.setattr(
        contribution_module.StatsRepository,
        "aggregated_player_stats",
        AsyncMock(return_value=[player]),
    )
    monkeypatch.setattr(
        contribution_module.StatsRepository,
        "attack_rows_for_players",
        AsyncMock(return_value=[(attack, war, stored_violation)]),
    )
    monkeypatch.setattr(
        contribution_module.StatsRepository,
        "participation_rows_for_players",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        contribution_module.StatsRepository,
        "enemy_participation_rows_for_wars",
        AsyncMock(return_value=[]),
    )

    return asyncio.run(
        DevContributionService(object(), app_yaml_config).build_contribution_calculation(period)
    )


@pytest.mark.parametrize("target", [15, 18])
def test_contribution_uses_absent_stored_violation_as_allowed_attack(
    app_yaml_config, monkeypatch, target
):
    calculation = _build_contribution_calculation_for_attack(
        app_yaml_config,
        monkeypatch,
        target=target,
        stored_violation=None,
    )

    component = next(
        item
        for item in calculation.components_by_tag["#DARK"]
        if item.kind == "attack"
    )

    assert component.violation_code is None
    assert component.score_delta == 48.0
    assert calculation.score_for("#DARK") == 48.0


def test_contribution_uses_saved_too_low_violation(app_yaml_config, monkeypatch):
    calculation = _build_contribution_calculation_for_attack(
        app_yaml_config,
        monkeypatch,
        target=18,
        stored_violation=SimpleNamespace(code=ViolationCode.TOO_LOW),
    )

    component = next(
        item
        for item in calculation.components_by_tag["#DARK"]
        if item.kind == "attack"
    )

    assert component.violation_code == ViolationCode.TOO_LOW
    assert component.score_delta == -40.0
    assert calculation.score_for("#DARK") == -40.0


def test_contribution_too_low_penalty_uses_plus_three_boundary(app_yaml_config, monkeypatch):
    calculation = _build_contribution_calculation_for_attack(
        app_yaml_config,
        monkeypatch,
        target=15,
        stored_violation=SimpleNamespace(code=ViolationCode.TOO_LOW),
        attacker_position=10,
    )

    component = next(
        item
        for item in calculation.components_by_tag["#DARK"]
        if item.kind == "attack"
    )

    assert component.violation_code == ViolationCode.TOO_LOW
    assert component.score_delta == -24.0
    assert calculation.score_for("#DARK") == -24.0


def test_contribution_does_not_infer_too_low_without_stored_violation(app_yaml_config, monkeypatch):
    calculation = _build_contribution_calculation_for_attack(
        app_yaml_config,
        monkeypatch,
        target=15,
        stored_violation=None,
        attacker_position=10,
    )

    component = next(
        item
        for item in calculation.components_by_tag["#DARK"]
        if item.kind == "attack"
    )

    assert component.violation_code is None
    assert component.score_delta == 48.0
    assert calculation.score_for("#DARK") == 48.0


def test_contribution_ignores_saved_automatic_violation_for_cwl(
    app_yaml_config, monkeypatch
):
    calculation = _build_contribution_calculation_for_attack(
        app_yaml_config,
        monkeypatch,
        target=18,
        stored_violation=SimpleNamespace(code=ViolationCode.TOO_LOW),
        war_type=WarType.CWL,
    )

    component = next(
        item
        for item in calculation.components_by_tag["#DARK"]
        if item.kind == "attack"
    )

    assert component.violation_code is None
    assert component.score_delta == 65.0


def test_unused_penalties():
    assert calculate_unused_attack_penalty(is_cwl=False, unused_attacks=1, attacker_position=1, opponent_positions=[1, 2, 3], attacked_defender_positions=[1, 2]) == -12
    assert calculate_unused_attack_penalty(is_cwl=False, unused_attacks=2, attacker_position=1, opponent_positions=[1, 2, 3], attacked_defender_positions=[1]) == -30
    assert calculate_unused_attack_penalty(is_cwl=False, unused_attacks=1, attacker_position=1, opponent_positions=[1, 2], attacked_defender_positions=[1, 2]) == 0
    assert calculate_unused_attack_penalty(is_cwl=True, unused_attacks=2, attacker_position=1, opponent_positions=[1, 2, 3], attacked_defender_positions=[1]) == 0


def test_cwl_unused_penalty():
    assert calculate_cwl_unused_attack_penalty(unused_attack=True, opponent_positions=[1, 2, 3], attacked_defender_positions=[1, 2]) == -40
    assert calculate_cwl_unused_attack_penalty(unused_attack=True, opponent_positions=[1, 2], attacked_defender_positions=[1, 2]) == 0
    assert calculate_cwl_unused_attack_penalty(unused_attack=False, opponent_positions=[1, 2], attacked_defender_positions=[]) == 0


def test_player_profile_dto_donations_parse():
    dto = PlayerProfileDTO.model_validate({"tag": "#A", "name": "A", "townHallLevel": 16, "donations": 10, "donationsReceived": 3})
    assert dto.donations == 10
    assert dto.donations_received == 3




def test_admin_menu_buttons_updated():
    flat = [b.text for row in main_menu(is_admin=True, is_registered=True).keyboard for b in row]
    assert "🧪 Dev-вклад" not in flat
    assert "🏆 Общий вклад" in flat
    assert "📋 Мой вклад" in flat
    assert "🧾 Разбор вклада" in flat
    assert "🏰 Столица" in flat
    assert "🧪 Dev-донаты" in flat
    assert "🚨 Нарушения" in flat
    assert "♻️ Сбросить счетчик нарушений" in flat


def test_public_contribution_button_and_admin_buttons_for_non_admin():
    flat = [b.text for row in main_menu(is_admin=False, is_registered=True).keyboard for b in row]
    assert "🏆 Общий вклад" in flat
    assert "📋 Мой вклад" in flat
    assert "🧾 Разбор вклада" not in flat
    assert "🚨 Нарушения" not in flat
    assert "♻️ Сбросить счетчик нарушений" not in flat
    assert "🏰 Столица" not in flat


def test_contribution_ranking_formats_only_total_score_and_statuses():
    service = DevContributionService(object(), SimpleNamespace(main_clan_tag="#CLAN"))

    text = service.format_contribution_ranking(
        [
            ContributionRankingRow(
                "#P1",
                "No Mark",
                1,
                160.45,
                False,
                donations=380,
                donation_points=3.8,
            ),
            ContributionRankingRow(
                "#P2",
                "Violation",
                1,
                120.0,
                False,
                active_violations=3,
                donations=200,
                donation_points=2.0,
            ),
            ContributionRankingRow(
                "#P3",
                "Newcomer",
                1,
                110.0,
                True,
                donations=100,
                donation_points=1.0,
            ),
            ContributionRankingRow(
                "#P4",
                "Both",
                1,
                100.0,
                True,
                active_violations=3,
                donations=50,
                donation_points=0.5,
            ),
        ]
    )

    assert text.splitlines() == [
        "🏆 Общий вклад",
        "",
        "1. No Mark — 160.45",
        "2. Violation — 120.00 ❌",
        "3. Newcomer — 110.00 🆕 новенький",
        "4. Both — 100.00 ❌ 🆕 новенький",
    ]
    assert "донат:" not in text
    assert "380" not in text
    assert "+3.80" not in text


def test_contribution_breakdown_still_formats_donation_component():
    breakdown = PlayerContributionBreakdown(
        player_tag="#P1",
        player_name="Donor",
        period_start=NOW - timedelta(days=1),
        period_end=NOW,
        attack_score_total=100.0,
        unused_attack_penalty_total=0.0,
        donation_total=380,
        donation_score_total=3.8,
        final_score=103.8,
        active_violations=0,
        manual_adjustment_total=0,
        items=[
            ContributionBreakdownItem(
                kind="donations",
                title="Донаты войск за цикл",
                occurred_at=None,
                score_delta=3.8,
                details="Сырой донат: 380",
            )
        ],
    )

    short_text = ContributionBreakdownService.format_short_breakdown(breakdown)
    detailed_text = ContributionBreakdownService.format_detailed_breakdown(breakdown)

    assert "Донаты: +3.80 (сырой донат: 380)" in short_text
    assert "Донаты войск за цикл | Сырой донат: 380" in detailed_text
    assert "+3.80" in detailed_text


def _build_test_app_context(app_yaml_config):
    class _Ctx:
        config = app_yaml_config
        auth_service = AuthService(app_yaml_config)

        @asynccontextmanager
        async def session_maker(self):
            yield object()

    return _Ctx()




def _mock_cycle(monkeypatch):
    monkeypatch.setattr("app.bot.handlers.admin.PeriodService.current_cycle", AsyncMock(return_value=SimpleNamespace(start=datetime.now(UTC)-timedelta(days=1), end=datetime.now(UTC))))


@pytest.mark.parametrize(
    ("raw_donations", "donation_points"),
    [(0, 0.0), (1, 0.01), (10, 0.1), (100, 1.0), (380, 3.8), (1000, 10.0)],
)
def test_contribution_ranking_adds_weighted_donations_to_base_score(
    app_yaml_config, monkeypatch, raw_donations, donation_points
):
    period = SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    war = SimpleNamespace(
        id=1,
        war_type=contribution_module.WarType.REGULAR,
        start_time=NOW - timedelta(hours=2),
        end_time=NOW - timedelta(minutes=1),
    )
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(
        contribution_module.StatsRepository,
        "attack_rows_for_players",
        AsyncMock(
            return_value=[
                (
                    SimpleNamespace(
                        attacker_tag="#P1",
                        stars=3,
                        destruction=100,
                        attacker_position=1,
                        defender_position=1,
                        observed_at=NOW,
                    ),
                    war,
                    None,
                )
            ]
        ),
    )
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module, "calculate_attack_contribution", Mock(return_value=SimpleNamespace(score=100.0)))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))
    donation_mock = AsyncMock(return_value=raw_donations)
    monkeypatch.setattr(DonationService, "calculate_player_donations_for_period", donation_mock)

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(period))

    assert ranking[0].score == 100.0 + donation_points
    assert ranking[0].donations == raw_donations
    assert ranking[0].donation_points == donation_points
    donation_mock.assert_awaited_once_with("#P1", period.start, period.end)


def test_contribution_ranking_without_donation_snapshots_keeps_base_score(app_yaml_config, monkeypatch):
    period = SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    war = SimpleNamespace(
        id=2,
        war_type=contribution_module.WarType.REGULAR,
        start_time=NOW - timedelta(hours=2),
        end_time=NOW - timedelta(minutes=1),
    )
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(
        contribution_module.StatsRepository,
        "attack_rows_for_players",
        AsyncMock(
            return_value=[
                (
                    SimpleNamespace(
                        attacker_tag="#P1",
                        stars=3,
                        destruction=100,
                        attacker_position=1,
                        defender_position=1,
                        observed_at=NOW,
                    ),
                    war,
                    None,
                )
            ]
        ),
    )
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module, "calculate_attack_contribution", Mock(return_value=SimpleNamespace(score=100.0)))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(period))

    assert ranking[0].score == 100.0
    assert ranking[0].donations == 0


def test_contribution_ranking_sorts_by_score_including_weighted_donations(
    app_yaml_config, monkeypatch
):
    period = SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)
    players = [
        SimpleNamespace(player_tag="#P1", player_name="Alpha", wars=1, player_id=1),
        SimpleNamespace(player_tag="#P2", player_name="Bravo", wars=1, player_id=2),
    ]
    war = SimpleNamespace(
        id=3,
        war_type=contribution_module.WarType.REGULAR,
        start_time=NOW - timedelta(hours=2),
        end_time=NOW - timedelta(minutes=1),
    )
    attacks = [
        (
            SimpleNamespace(
                attacker_tag=player.player_tag,
                stars=3,
                destruction=100,
                attacker_position=1,
                defender_position=index,
                observed_at=NOW,
            ),
            war,
            None,
        )
        for index, player in enumerate(players, 1)
    ]
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=players))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=attacks))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        contribution_module,
        "calculate_attack_contribution",
        Mock(side_effect=[SimpleNamespace(score=100.0), SimpleNamespace(score=90.0)]),
    )
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))
    monkeypatch.setattr(
        DonationService,
        "calculate_player_donations_for_period",
        AsyncMock(
            side_effect=lambda player_tag, _start, _end: {
                "#P1": 0,
                "#P2": 2000,
            }[player_tag]
        ),
    )

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(period))

    assert [(row.player_tag, row.score) for row in ranking] == [("#P2", 110.0), ("#P1", 100.0)]


def test_dev_donations_button_keeps_separate_ranking(app_yaml_config, monkeypatch):
    ranking = [SimpleNamespace(player_name="Donor", player_tag="#P1", donations=37)]
    build_mock = AsyncMock(return_value=ranking)
    format_mock = Mock(return_value="🧪 Dev-донаты\n\n1. Donor — 37")
    monkeypatch.setattr(DonationService, "build_current_cycle_donation_ranking", build_mock)
    monkeypatch.setattr(DonationService, "format_donation_ranking", format_mock)
    message = FakeMessage("🧪 Dev-донаты", user_id=1)

    asyncio.run(dev_donations(message, _build_test_app_context(app_yaml_config)))

    build_mock.assert_awaited_once_with()
    format_mock.assert_called_once_with(ranking)
    message.answer.assert_awaited_once_with("🧪 Dev-донаты\n\n1. Donor — 37")

def test_dev_contribution_no_attacks_returns_user_message(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[SimpleNamespace(player_tag="#P1", player_name="P1", wars=0, player_id=1)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[]))
    message = FakeMessage("🏆 Общий вклад", user_id=1)

    asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))

    message.answer.assert_called_once_with("⚠️ Общий вклад пока недоступен: в текущем цикле еще недостаточно данных.")


def test_dev_contribution_all_zero_still_builds_report(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=0, player_id=1)
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(attacker_tag="#P1", stars=0, destruction=0, attacker_position=1, defender_position=1, observed_at=NOW), SimpleNamespace(id=1, war_type=SimpleNamespace(value="random"), start_time=NOW - timedelta(hours=1), end_time=NOW + timedelta(hours=1)), None)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))
    message = FakeMessage("🏆 Общий вклад", user_id=1)

    asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))

    sent_text = message.answer.call_args_list[0].args[0]
    assert "🏆 Общий вклад" in sent_text
    assert "0.00" in sent_text


def test_dev_contribution_mixed_players_with_and_without_stars_builds_report(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    p1 = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    p2 = SimpleNamespace(player_tag="#P2", player_name="P2", wars=0, player_id=2)
    war = SimpleNamespace(id=1, war_type=SimpleNamespace(value="random"), start_time=NOW - timedelta(hours=1), end_time=NOW - timedelta(minutes=1))
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[p1, p2]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(attacker_tag="#P1", stars=3, destruction=100, attacker_position=1, defender_position=1, observed_at=NOW), war, None)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))

    async def newcomer_side_effect(player_id, as_of=None):
        return player_id == 2

    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(side_effect=newcomer_side_effect))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=datetime.now(UTC)-timedelta(days=1), end=datetime.now(UTC))))
    assert len(ranking) == 2
    assert ranking[0].player_tag == "#P1"
    assert ranking[1].newcomer is True


def test_dev_contribution_applies_regular_unused_attack_penalty(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    war = SimpleNamespace(id=10, war_type=contribution_module.WarType.REGULAR, start_time=NOW - timedelta(hours=1), end_time=NOW - timedelta(minutes=1))
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(attacker_tag="#P1", stars=2, destruction=80, attacker_position=5, defender_position=5, observed_at=NOW), war, None)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(player_tag="#P1", map_position=1), war)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[SimpleNamespace(war_id=10, map_position=1), SimpleNamespace(war_id=10, map_position=2), SimpleNamespace(war_id=10, map_position=3)]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=datetime.now(UTC)-timedelta(days=1), end=datetime.now(UTC))))
    assert ranking[0].score == 16.0


def test_dev_contribution_applies_cwl_unused_attack_penalty(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    ally = SimpleNamespace(player_tag="#ALLY", player_name="Ally", wars=1, player_id=2)
    war = SimpleNamespace(id=20, war_type=contribution_module.WarType.CWL, end_time=NOW - timedelta(minutes=1))
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player, ally]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(attacker_tag="#ALLY", stars=1, destruction=20, attacker_position=2, defender_position=1, observed_at=NOW), war, None)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(player_tag="#P1", map_position=1), war)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[SimpleNamespace(war_id=20, map_position=1), SimpleNamespace(war_id=20, map_position=2)]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=datetime.now(UTC)-timedelta(days=1), end=datetime.now(UTC))))
    by_tag = {row.player_tag: row.score for row in ranking}
    assert by_tag["#P1"] == -40.0


def test_dev_contribution_empty_players_returns_user_message(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[]))
    message = FakeMessage("🏆 Общий вклад", user_id=1)

    asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))

    message.answer.assert_called_once_with("⚠️ Общий вклад пока недоступен: в текущем цикле еще недостаточно данных.")


def test_dev_contribution_datetime_error_returns_cycle_safe_message(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    monkeypatch.setattr(DevContributionService, "build_contribution_ranking", AsyncMock(side_effect=TypeError("can't compare offset-naive and offset-aware datetimes")))
    message = FakeMessage("🏆 Общий вклад", user_id=1)

    asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))

    message.answer.assert_called_once_with("⚠️ Общий вклад пока недоступен: в текущем цикле еще недостаточно данных.")


def test_is_newcomer_continuous_less_than_seven_days():
    now_aware = datetime.now(UTC)

    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return [SimpleNamespace(joined_at=now_aware - timedelta(days=6), left_at=None)]

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10)) is True


def test_is_newcomer_continuous_seven_days_or_more_is_false():
    now_aware = datetime.now(UTC)

    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return [SimpleNamespace(joined_at=now_aware - timedelta(days=7), left_at=None)]

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10)) is False


def test_is_newcomer_sum_three_and_three_days_is_true():
    now_aware = datetime.now(UTC)

    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return [
                SimpleNamespace(joined_at=now_aware - timedelta(days=14), left_at=now_aware - timedelta(days=11)),
                SimpleNamespace(joined_at=now_aware - timedelta(days=3), left_at=None),
            ]

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10)) is True


def test_is_newcomer_sum_four_and_four_days_is_false():
    now_aware = datetime.now(UTC)

    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return [
                SimpleNamespace(joined_at=now_aware - timedelta(days=14), left_at=now_aware - timedelta(days=10)),
                SimpleNamespace(joined_at=now_aware - timedelta(days=4), left_at=None),
            ]

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10)) is False


def test_is_newcomer_long_ago_joined_but_large_gap_uses_actual_sum():
    now_aware = datetime.now(UTC)

    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return [
                SimpleNamespace(joined_at=now_aware - timedelta(days=60), left_at=now_aware - timedelta(days=57)),
                SimpleNamespace(joined_at=now_aware - timedelta(days=2), left_at=None),
            ]

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10)) is True


def test_is_newcomer_open_interval_is_counted_until_now():
    now_aware = datetime.now(UTC)

    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return [SimpleNamespace(joined_at=now_aware - timedelta(days=2), left_at=None)]

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    total = asyncio.run(service.get_total_membership_duration(10))
    assert total is not None
    assert total >= timedelta(days=2)


def test_is_newcomer_accepts_naive_and_aware_membership_datetimes():
    now_aware = datetime.now(UTC)

    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return [
                SimpleNamespace(joined_at=(now_aware - timedelta(days=2)).replace(tzinfo=None), left_at=(now_aware - timedelta(days=1)).replace(tzinfo=None)),
                SimpleNamespace(joined_at=now_aware - timedelta(days=1), left_at=None),
            ]

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10)) is True


def test_is_newcomer_without_any_membership_data_is_false():
    class DummySession:
        async def scalars(self, *_args, **_kwargs):
            return []

        async def scalar(self, *_args, **_kwargs):
            return None

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10)) is False


def test_dev_contribution_unexpected_error_logged_and_safe_message(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    monkeypatch.setattr(DevContributionService, "build_contribution_ranking", AsyncMock(side_effect=RuntimeError("boom")))
    message = FakeMessage("🏆 Общий вклад", user_id=1)
    with pytest.MonkeyPatch.context() as mp:
        mock_exception = Mock()
        mp.setattr("app.bot.handlers.admin.logger.exception", mock_exception)
        asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))
        mock_exception.assert_called_once()

    message.answer.assert_called_once_with("⚠️ Не удалось построить отчет по общему вкладу. Попробуйте позже.")


def test_dev_contribution_handler_always_answers(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    monkeypatch.setattr(DevContributionService, "build_contribution_ranking", AsyncMock(side_effect=ContributionDataUnavailableError("⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет данных по атакам.")))
    message = FakeMessage("🏆 Общий вклад", user_id=1)

    asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))

    assert message.answer.await_count == 1


def test_contribution_ranking_tie_break_is_stable(app_yaml_config, monkeypatch):
    player_b = SimpleNamespace(player_tag="#B", player_name="Bravo", wars=1, player_id=1)
    player_a = SimpleNamespace(player_tag="#A", player_name="Alpha", wars=1, player_id=2)
    war = SimpleNamespace(id=99, war_type=contribution_module.WarType.REGULAR, start_time=NOW - timedelta(hours=1), end_time=NOW - timedelta(minutes=1))

    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player_b, player_a]))
    monkeypatch.setattr(
        contribution_module.StatsRepository,
        "attack_rows_for_players",
        AsyncMock(
            return_value=[
                    (SimpleNamespace(attacker_tag="#A", stars=2, destruction=80, attacker_position=1, defender_position=1, observed_at=NOW), war, None),
                    (SimpleNamespace(attacker_tag="#B", stars=2, destruction=80, attacker_position=1, defender_position=1, observed_at=NOW), war, None),
                ]
            ),
        )
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=datetime.now(UTC)-timedelta(days=1), end=datetime.now(UTC))))
    assert [row.player_tag for row in ranking] == ["#A", "#B"]


def test_build_contribution_ranking_allows_one_position_above(app_yaml_config, monkeypatch):
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    war = SimpleNamespace(id=101, war_type=contribution_module.WarType.REGULAR, start_time=NOW - timedelta(hours=2), end_time=NOW - timedelta(minutes=1))
    attacks = [
        (SimpleNamespace(attacker_tag="#P1", stars=3, destruction=100, attacker_position=5, defender_position=5, observed_at=NOW), war, None),
        (SimpleNamespace(attacker_tag="#P1", stars=3, destruction=100, attacker_position=10, defender_position=9, observed_at=NOW), war, None),
    ]
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=attacks))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)))
    assert ranking[0].score == 96.0




def test_build_contribution_ranking_real_cases_for_timon_and_0b_sos(app_yaml_config, monkeypatch):
    p1 = SimpleNamespace(player_tag="#TIMON", player_name="timon", wars=1, player_id=1)
    p2 = SimpleNamespace(player_tag="#SOS", player_name="0b_sos", wars=1, player_id=2)
    war = SimpleNamespace(id=103, war_type=contribution_module.WarType.REGULAR, start_time=NOW - timedelta(hours=2), end_time=NOW - timedelta(minutes=1))
    attacks = [
        (SimpleNamespace(attacker_tag="#TIMON", stars=3, destruction=100, attacker_position=10, defender_position=9, observed_at=NOW), war, None),
        (SimpleNamespace(attacker_tag="#TIMON", stars=3, destruction=100, attacker_position=11, defender_position=10, observed_at=NOW), war, None),
        (SimpleNamespace(attacker_tag="#SOS", stars=1, destruction=93, attacker_position=15, defender_position=15, observed_at=NOW), war, None),
        (SimpleNamespace(attacker_tag="#SOS", stars=3, destruction=100, attacker_position=20, defender_position=19, observed_at=NOW), war, None),
    ]
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[p1, p2]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=attacks))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)))
    by_tag = {row.player_tag: row.score for row in ranking}
    assert by_tag["#TIMON"] == 96.0
    assert by_tag["#SOS"] == 67.3

def test_build_contribution_ranking_keeps_cwl_without_positional_penalties(app_yaml_config, monkeypatch):
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    war = SimpleNamespace(id=102, war_type=contribution_module.WarType.CWL, start_time=NOW - timedelta(hours=2), end_time=NOW - timedelta(minutes=1))
    attacks = [(SimpleNamespace(attacker_tag="#P1", stars=3, destruction=100, attacker_position=10, defender_position=1, observed_at=NOW), war, None)]
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=attacks))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)))
    assert ranking[0].score == 65.0

def test_repeated_target_after_prior_triple_gets_only_half_star_component():
    result = calculate_attack_contribution(
        ContributionAttackInput(
            stars=3,
            destruction=100,
            attacker_position=1,
            defender_position=1,
            is_cwl=False,
            previous_best_stars=3,
            previous_best_destruction=100,
            target_already_attacked=True,
        )
    )
    assert result.score == 15.0


def test_repeated_target_improvement_uses_best_previous_baseline_and_keeps_triple_bonus():
    result = calculate_attack_contribution(
        ContributionAttackInput(
            stars=3,
            destruction=90,
            attacker_position=1,
            defender_position=1,
            is_cwl=False,
            previous_best_stars=1,
            previous_best_destruction=40,
            target_already_attacked=True,
        )
    )
    assert result.score == 40.0


def test_repeated_target_after_only_zero_stars_uses_regular_formula():
    result = calculate_attack_contribution(
        ContributionAttackInput(
            stars=2,
            destruction=80,
            attacker_position=1,
            defender_position=1,
            is_cwl=False,
            previous_best_stars=0,
            previous_best_destruction=70,
            target_already_attacked=True,
        )
    )
    assert result.score == 28.0


def test_dev_contribution_skips_regular_unused_penalty_before_war_end(app_yaml_config, monkeypatch):
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    war = SimpleNamespace(id=110, war_type=contribution_module.WarType.REGULAR, start_time=NOW - timedelta(hours=1), end_time=NOW + timedelta(hours=4))
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(attacker_tag="#P1", stars=2, destruction=80, attacker_position=5, defender_position=5, observed_at=NOW), war, None)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(player_tag="#P1", map_position=1), war)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[SimpleNamespace(war_id=110, map_position=1), SimpleNamespace(war_id=110, map_position=2)]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)))
    assert ranking[0].score == 28.0


def test_dev_contribution_skips_cwl_unused_penalty_before_war_end(app_yaml_config, monkeypatch):
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    ally = SimpleNamespace(player_tag="#ALLY", player_name="Ally", wars=1, player_id=2)
    war = SimpleNamespace(id=120, war_type=contribution_module.WarType.CWL, end_time=NOW + timedelta(hours=3))
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player, ally]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(attacker_tag="#ALLY", stars=1, destruction=20, attacker_position=2, defender_position=1, observed_at=NOW), war, None)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(player_tag="#P1", map_position=1), war)]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[SimpleNamespace(war_id=120, map_position=1), SimpleNamespace(war_id=120, map_position=2)]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)))
    by_tag = {row.player_tag: row.score for row in ranking}
    assert by_tag["#P1"] == 0.0

def test_select_best_attack_result_prefers_stars_over_destruction():
    assert contribution_module._select_best_attack_result([(2, 60.0), (1, 90.0)]) == (2, 60.0)


def test_select_best_attack_result_prefers_higher_destruction_on_equal_stars():
    assert contribution_module._select_best_attack_result([(2, 60.0), (2, 75.0)]) == (2, 75.0)


def test_select_best_attack_result_prefers_higher_stars_even_with_lower_destruction():
    assert contribution_module._select_best_attack_result([(1, 90.0), (2, 40.0)]) == (2, 40.0)


def test_select_best_attack_result_returns_zero_baseline_when_empty():
    assert contribution_module._select_best_attack_result([]) == (0, 0.0)


def test_build_contribution_ranking_uses_only_previous_attacks_for_baseline(app_yaml_config, monkeypatch):
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=1, player_id=1)
    war = SimpleNamespace(id=130, war_type=contribution_module.WarType.REGULAR, start_time=NOW - timedelta(hours=2), end_time=NOW - timedelta(minutes=1))
    attacks = [
        (SimpleNamespace(attacker_tag="#P1", stars=2, destruction=60, attacker_position=5, defender_position=5, observed_at=NOW), war, None),
        (SimpleNamespace(attacker_tag="#P1", stars=1, destruction=90, attacker_position=5, defender_position=5, observed_at=NOW + timedelta(seconds=1)), war, None),
        (SimpleNamespace(attacker_tag="#P1", stars=2, destruction=70, attacker_position=5, defender_position=5, observed_at=NOW + timedelta(seconds=2)), war, None),
    ]

    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=attacks))
    monkeypatch.setattr(contribution_module.StatsRepository, "participation_rows_for_players", AsyncMock(return_value=[]))
    monkeypatch.setattr(contribution_module.StatsRepository, "enemy_participation_rows_for_wars", AsyncMock(return_value=[]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    ranking = asyncio.run(DevContributionService(object(), app_yaml_config).build_contribution_ranking(SimpleNamespace(start=NOW - timedelta(days=1), end=NOW)))

    assert ranking[0].score == 51.0



def _menu_texts(markup):
    return [button.text for row in markup.keyboard for button in row]


def test_previous_cycle_contribution_button_is_public():
    for menu in (
        main_menu(is_admin=False, is_registered=True),
        main_menu(is_admin=True, is_registered=True),
        main_menu(is_admin=False, is_registered=False),
    ):
        flat = _menu_texts(menu)
        assert "📚 Вклад прошлого цикла" in flat
        assert flat.index("🏆 Общий вклад") < flat.index("📚 Вклад прошлого цикла") < flat.index("📋 Мой вклад")


def test_previous_cycle_contribution_uses_previous_cycle(app_yaml_config, monkeypatch):
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
    ranking = [object()]
    monkeypatch.setattr("app.bot.handlers.admin.PeriodService.previous_cycle", AsyncMock(return_value=period))
    monkeypatch.setattr(DevContributionService, "build_contribution_ranking", AsyncMock(return_value=ranking))
    monkeypatch.setattr(DevContributionService, "format_contribution_ranking", Mock(return_value="report"))
    message = FakeMessage("📚 Вклад прошлого цикла", user_id=99)

    asyncio.run(previous_cycle_contribution(message, _build_test_app_context(app_yaml_config)))

    contribution_module.DevContributionService.build_contribution_ranking.assert_awaited_once_with(period, include_historical_members=True)
    contribution_module.DevContributionService.format_contribution_ranking.assert_called_once_with(
        ranking,
        title="🏆 Общий вклад за прошлый цикл",
        period=period,
    )
    message.answer.assert_called_once_with("report")


def test_previous_cycle_contribution_does_not_use_current_cycle(app_yaml_config, monkeypatch):
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
    previous = AsyncMock(return_value=period)
    current = AsyncMock()
    monkeypatch.setattr("app.bot.handlers.admin.PeriodService.previous_cycle", previous)
    monkeypatch.setattr("app.bot.handlers.admin.PeriodService.current_cycle", current)
    monkeypatch.setattr(DevContributionService, "build_contribution_ranking", AsyncMock(return_value=[]))
    monkeypatch.setattr(DevContributionService, "format_contribution_ranking", Mock(return_value="report"))
    message = FakeMessage("📚 Вклад прошлого цикла", user_id=99)

    asyncio.run(previous_cycle_contribution(message, _build_test_app_context(app_yaml_config)))

    previous.assert_awaited_once_with()
    current.assert_not_called()


def test_previous_cycle_contribution_missing_boundaries_returns_safe_message(app_yaml_config, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.admin.PeriodService.previous_cycle",
        AsyncMock(side_effect=ValueError("Прошлый цикл недоступен: в базе недостаточно границ циклов ЛВК")),
    )
    message = FakeMessage("📚 Вклад прошлого цикла", user_id=99)

    asyncio.run(previous_cycle_contribution(message, _build_test_app_context(app_yaml_config)))

    message.answer.assert_called_once_with("⚠️ Общий вклад за прошлый цикл недоступен: в базе недостаточно границ циклов ЛВК.")


def test_previous_cycle_contribution_without_data_returns_safe_message(app_yaml_config, monkeypatch):
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
    monkeypatch.setattr("app.bot.handlers.admin.PeriodService.previous_cycle", AsyncMock(return_value=period))
    monkeypatch.setattr(
        DevContributionService,
        "build_contribution_ranking",
        AsyncMock(side_effect=ContributionDataUnavailableError("в текущем цикле нет данных")),
    )
    message = FakeMessage("📚 Вклад прошлого цикла", user_id=99)

    asyncio.run(previous_cycle_contribution(message, _build_test_app_context(app_yaml_config)))

    message.answer.assert_called_once_with("⚠️ Общий вклад за прошлый цикл недоступен: за прошлый цикл недостаточно данных.")
    assert "текущий цикл" not in message.answer.call_args.args[0]


def test_previous_cycle_contribution_unexpected_error_is_logged(app_yaml_config, monkeypatch):
    monkeypatch.setattr("app.bot.handlers.admin.PeriodService.previous_cycle", AsyncMock(side_effect=RuntimeError("boom")))
    logger = Mock()
    monkeypatch.setattr("app.bot.handlers.admin.logger", logger)
    message = FakeMessage("📚 Вклад прошлого цикла", user_id=99)

    asyncio.run(previous_cycle_contribution(message, _build_test_app_context(app_yaml_config)))

    logger.exception.assert_called_once_with("Failed to build previous cycle contribution report")
    message.answer.assert_called_once_with("⚠️ Не удалось построить отчет по общему вкладу за прошлый цикл. Попробуйте позже.")


def test_previous_cycle_contribution_format_contains_title_and_dates():
    service = DevContributionService(object(), SimpleNamespace(main_clan_tag="#CLAN"))
    period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
    text = service.format_contribution_ranking(
        [ContributionRankingRow("#P1", "Alpha", 1, 100.0, False)],
        title="🏆 Общий вклад за прошлый цикл",
        period=period,
    )
    assert text.splitlines() == [
        "🏆 Общий вклад за прошлый цикл",
        "📅 01.05.2026 — 01.06.2026",
        "",
        "1. Alpha — 100.00",
    ]


def test_current_contribution_format_is_unchanged_without_period():
    service = DevContributionService(object(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert service.format_contribution_ranking([ContributionRankingRow("#P1", "Alpha", 1, 100.0, False)]) == "🏆 Общий вклад\n\n1. Alpha — 100.00"


def _player(tag, name, *, in_clan=False, clan="#CLAN"):
    return PlayerAccount(player_tag=tag, name=name, town_hall=16, current_clan_tag=clan, current_clan_name="Clan", current_clan_rank=1, current_in_clan=in_clan, created_at=NOW, updated_at=NOW)


def _war(uid, period):
    return War(war_uid=uid, clan_tag="#CLAN", clan_name="Clan", opponent_tag="#OP", opponent_name="Opp", war_type=WarType.REGULAR, state=WarState.WAR_ENDED, team_size=1, is_friendly=False, start_time=period.start + timedelta(days=1), end_time=period.start + timedelta(days=2), source_payload={})


def _attack(player, war, period):
    return Attack(war=war, attacker=player, attacker_tag=player.player_tag, attacker_name=player.name, attacker_position=1, attacker_town_hall=16, defender_tag="#D", defender_name="D", defender_position=1, defender_town_hall=16, stars=3, destruction=100, attack_order=1, observed_at=period.start + timedelta(days=1, hours=1))



async def _with_test_session(tmp_path, scenario):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'previous_cycle.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as session:
            return await scenario(session)
    finally:
        await engine.dispose()


def test_previous_cycle_ranking_includes_player_who_left_after_cycle(tmp_path, app_yaml_config):
    async def scenario(session):
        period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
        player = _player("#LEFT", "Left", in_clan=False)
        war = _war("w-left", period)
        session.add_all([player, war])
        await session.flush()
        session.add_all([ClanMembershipHistory(player_id=player.id, clan_tag="#CLAN", joined_at=period.start - timedelta(days=2), left_at=period.end + timedelta(days=1)), _attack(player, war, period)])
        await session.commit()
        ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(period, include_historical_members=True)
        assert "#LEFT" in {row.player_tag for row in ranking}

    asyncio.run(_with_test_session(tmp_path, scenario))


def test_previous_cycle_ranking_excludes_player_joined_after_cycle(tmp_path, app_yaml_config):
    async def scenario(session):
        period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
        player = _player("#AFTER", "After", in_clan=False)
        valid = _player("#VALID", "Valid", in_clan=False)
        war = _war("w-after", period)
        session.add_all([player, valid, war])
        await session.flush()
        session.add_all([
            ClanMembershipHistory(player_id=valid.id, clan_tag="#CLAN", joined_at=period.start - timedelta(days=1), left_at=None),
            ClanMembershipHistory(player_id=player.id, clan_tag="#CLAN", joined_at=period.end + timedelta(days=1), left_at=None),
            _attack(player, war, period),
            _attack(valid, war, period),
        ])
        await session.commit()
        ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(period, include_historical_members=True)
        assert "#AFTER" not in {row.player_tag for row in ranking}

    asyncio.run(_with_test_session(tmp_path, scenario))


def test_previous_cycle_ranking_excludes_membership_in_another_clan(tmp_path, app_yaml_config):
    async def scenario(session):
        period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
        player = _player("#OTHER", "Other", in_clan=False, clan="#OTHER")
        valid = _player("#VALID", "Valid", in_clan=False)
        war = _war("w-other", period)
        session.add_all([player, valid, war])
        await session.flush()
        session.add_all([
            ClanMembershipHistory(player_id=valid.id, clan_tag="#CLAN", joined_at=period.start - timedelta(days=1), left_at=None),
            ClanMembershipHistory(player_id=player.id, clan_tag="#OTHER", joined_at=period.start - timedelta(days=1), left_at=None),
            _attack(player, war, period),
            _attack(valid, war, period),
        ])
        await session.commit()
        ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(period, include_historical_members=True)
        assert "#OTHER" not in {row.player_tag for row in ranking}

    asyncio.run(_with_test_session(tmp_path, scenario))


def test_current_contribution_still_uses_current_members_only(tmp_path, app_yaml_config):
    async def scenario(session):
        period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
        player = _player("#LEFTNOW", "LeftNow", in_clan=False)
        war = _war("w-current", period)
        session.add_all([player, war])
        await session.flush()
        session.add_all([ClanMembershipHistory(player_id=player.id, clan_tag="#CLAN", joined_at=period.start - timedelta(days=1), left_at=None), _attack(player, war, period)])
        await session.commit()
        with pytest.raises(ContributionDataUnavailableError):
            await DevContributionService(session, app_yaml_config).build_contribution_ranking(period)

    asyncio.run(_with_test_session(tmp_path, scenario))


def test_newcomer_status_is_calculated_at_previous_cycle_end(tmp_path, app_yaml_config):
    async def scenario(session):
        period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
        player = _player("#NEW", "New", in_clan=True)
        war = _war("w-new", period)
        session.add_all([player, war])
        await session.flush()
        session.add_all([ClanMembershipHistory(player_id=player.id, clan_tag="#CLAN", joined_at=period.end - timedelta(days=3), left_at=None), _attack(player, war, period)])
        await session.commit()
        ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(period, include_historical_members=True)
        assert ranking[0].newcomer is True

    asyncio.run(_with_test_session(tmp_path, scenario))


def test_membership_after_period_end_does_not_affect_previous_newcomer_status(tmp_path, app_yaml_config):
    async def scenario(session):
        period = SimpleNamespace(start=datetime(2026, 5, 1, tzinfo=UTC), end=datetime(2026, 6, 1, tzinfo=UTC))
        player = _player("#OLD", "Old", in_clan=True)
        war = _war("w-old", period)
        session.add_all([player, war])
        await session.flush()
        session.add_all([
            ClanMembershipHistory(player_id=player.id, clan_tag="#CLAN", joined_at=period.end - timedelta(days=8), left_at=period.end - timedelta(days=1)),
            ClanMembershipHistory(player_id=player.id, clan_tag="#CLAN", joined_at=period.end + timedelta(days=1), left_at=None),
            _attack(player, war, period),
        ])
        await session.commit()
        ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(period, include_historical_members=True)
        assert ranking[0].newcomer is False

    asyncio.run(_with_test_session(tmp_path, scenario))

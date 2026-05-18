from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.bot.handlers.admin import dev_contribution, dev_donations
from app.bot.keyboards.main import main_menu
from app.domain.dev_contribution import (
    ContributionAttackInput,
    calculate_attack_contribution,
    calculate_cwl_unused_attack_penalty,
    calculate_unused_attack_penalty,
)
from app.schemas.dto import PlayerProfileDTO
from app.services import dev_contribution as contribution_module
from app.services.dev_contribution import ContributionDataUnavailableError, ContributionRankingRow, DevContributionService
from app.services.auth import AuthService
from app.services.donations import DonationService
from tests.fakes import FakeMessage


NOW = datetime.now(UTC)


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
    assert "🏰 Столица" in flat
    assert "🧪 Dev-донаты" in flat
    assert "🚨 Нарушения" in flat


def test_violations_button_hidden_for_non_admin():
    flat = [b.text for row in main_menu(is_admin=False, is_registered=True).keyboard for b in row]
    assert "🚨 Нарушения" not in flat
    assert "🏰 Столица" not in flat


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

    async def newcomer_side_effect(_player_id, score, wars):
        return score == 0 and wars == 0

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


def test_build_contribution_ranking_recomputes_above_self_without_persisted_violation(app_yaml_config, monkeypatch):
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
    assert ranking[0].score == 88.0




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
    assert by_tag["#TIMON"] == 80.0
    assert by_tag["#SOS"] == 59.3

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

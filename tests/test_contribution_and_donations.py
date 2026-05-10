from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncio
from contextlib import asynccontextmanager

import pytest

from app.bot.handlers.admin import dev_contribution, dev_donations
from app.bot.keyboards.main import main_menu
from app.domain.dev_contribution import ContributionAttackInput, calculate_attack_contribution, calculate_unused_attack_penalty
from app.schemas.dto import PlayerProfileDTO
from app.services import dev_contribution as contribution_module
from app.services.dev_contribution import ContributionDataUnavailableError, ContributionRankingRow, DevContributionService
from app.services.auth import AuthService
from app.services.donations import DonationService
from tests.fakes import FakeMessage


def test_contribution_formulas():
    assert calculate_attack_contribution(ContributionAttackInput(stars=2, destruction=80, attacker_position=1, defender_position=1, is_cwl=False)).score == 28
    assert calculate_attack_contribution(ContributionAttackInput(stars=2, destruction=80, attacker_position=1, defender_position=1, is_cwl=False, is_above_self_violation=True)).score == -8
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=1, defender_position=1, is_cwl=False, is_above_self_violation=True)).score == 40
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=1, defender_position=20, is_cwl=False, is_too_low_violation=True)).score < 0
    assert calculate_attack_contribution(ContributionAttackInput(stars=1, destruction=30, attacker_position=1, defender_position=20, is_cwl=False, is_too_low_violation=True)).score == -40
    assert calculate_attack_contribution(ContributionAttackInput(stars=3, destruction=100, attacker_position=1, defender_position=20, is_cwl=True, is_too_low_violation=True, is_above_self_violation=True)).score == 65.0


def test_unused_penalties():
    assert calculate_unused_attack_penalty(is_cwl=False, unused_attacks=1, attacker_position=1, opponent_positions=[1, 2, 3], attacked_defender_positions=[1, 2]) == -12
    assert calculate_unused_attack_penalty(is_cwl=False, unused_attacks=2, attacker_position=1, opponent_positions=[1, 2, 3], attacked_defender_positions=[1]) == -30
    assert calculate_unused_attack_penalty(is_cwl=False, unused_attacks=1, attacker_position=1, opponent_positions=[1, 2], attacked_defender_positions=[1, 2]) == 0
    assert calculate_unused_attack_penalty(is_cwl=True, unused_attacks=2, attacker_position=1, opponent_positions=[1, 2, 3], attacked_defender_positions=[1]) == 0


def test_player_profile_dto_donations_parse():
    dto = PlayerProfileDTO.model_validate({"tag": "#A", "name": "A", "townHallLevel": 16, "donations": 10, "donationsReceived": 3})
    assert dto.donations == 10
    assert dto.donations_received == 3




def test_admin_menu_buttons_updated():
    flat = [b.text for row in main_menu(is_admin=True, is_registered=True).keyboard for b in row]
    assert "🧪 Dev-вклад" not in flat
    assert "🏆 Общий вклад" in flat
    assert "🧪 Dev-донаты" in flat


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

    message.answer.assert_called_once_with("⚠️ Общий вклад пока пуст: в текущем цикле еще никто не сделал атак.")


def test_dev_contribution_all_zero_still_builds_report(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    player = SimpleNamespace(player_tag="#P1", player_name="P1", wars=0, player_id=1)
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[player]))
    monkeypatch.setattr(contribution_module.StatsRepository, "attack_rows_for_players", AsyncMock(return_value=[(SimpleNamespace(attacker_tag="#P1", stars=0, destruction=0, attacker_position=1, defender_position=1), SimpleNamespace(war_type=SimpleNamespace(value="random")), None)]))
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))
    message = FakeMessage("🏆 Общий вклад", user_id=1)

    asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))

    sent_text = message.answer.call_args_list[0].args[0]
    assert "🏆 Общий вклад" in sent_text
    assert "0.00" in sent_text


def test_dev_contribution_empty_players_returns_user_message(app_yaml_config, monkeypatch):
    _mock_cycle(monkeypatch)
    monkeypatch.setattr(contribution_module.StatsRepository, "aggregated_player_stats", AsyncMock(return_value=[]))
    message = FakeMessage("🏆 Общий вклад", user_id=1)

    asyncio.run(dev_contribution(message, _build_test_app_context(app_yaml_config)))

    message.answer.assert_called_once_with("⚠️ Общий вклад пока нельзя посчитать: в текущем цикле еще нет игроков в основном клане.")


def test_newcomer_mark_with_zero_score_and_zero_wars(monkeypatch):
    class DummySession:
        async def scalar(self, *_args, **_kwargs):
            return SimpleNamespace(joined_at=datetime.now(UTC) - timedelta(days=5))

    service = DevContributionService(DummySession(), SimpleNamespace(main_clan_tag="#CLAN"))
    assert asyncio.run(service.is_newcomer(10, 0.0, 0)) is True


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

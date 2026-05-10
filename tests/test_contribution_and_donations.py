from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.bot.handlers.admin import dev_donations
from app.bot.keyboards.main import main_menu
from app.domain.dev_contribution import ContributionAttackInput, calculate_attack_contribution, calculate_unused_attack_penalty
from app.schemas.dto import PlayerProfileDTO
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

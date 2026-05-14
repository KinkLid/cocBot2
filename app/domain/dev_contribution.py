from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ContributionAttackInput:
    stars: int
    destruction: float
    attacker_position: int
    defender_position: int
    is_cwl: bool
    previous_best_stars: int = 0
    previous_best_destruction: float = 0.0
    target_already_attacked: bool = False
    is_above_self_violation: bool = False
    is_too_low_violation: bool = False


@dataclass(slots=True)
class ContributionPlayerInput:
    attacks: list[ContributionAttackInput]
    unused_attacks: int
    attacker_position: int
    is_cwl: bool
    opponent_positions: list[int]
    attacked_defender_positions: list[int]


@dataclass(slots=True)
class ContributionResult:
    score: float


def calculate_attack_contribution(data: ContributionAttackInput) -> ContributionResult:
    triple_bonus = 12 if data.is_cwl else 8

    if data.target_already_attacked and data.previous_best_stars >= 3:
        base_score = data.stars * 10 * 0.5
        allow_triple_bonus = False
    elif data.target_already_attacked and data.previous_best_stars > 0:
        overlap_stars = min(data.previous_best_stars, data.stars)
        new_stars = max(data.stars - data.previous_best_stars, 0)
        stars_component = overlap_stars * 10 * 0.5 + new_stars * 10

        overlap_destruction = min(data.previous_best_destruction, data.destruction)
        new_destruction = max(data.destruction - data.previous_best_destruction, 0)
        destruction_component = overlap_destruction / 10 * 0.5 + new_destruction / 10

        base_score = stars_component + destruction_component
        allow_triple_bonus = True
    else:
        base_score = data.stars * 10 + data.destruction / 10
        allow_triple_bonus = True

    if data.is_cwl:
        return ContributionResult(score=round((base_score + (triple_bonus if data.stars == 3 and allow_triple_bonus else 0)) * 1.25, 2))

    if data.is_above_self_violation:
        score = 0 if data.stars < 3 else base_score
    else:
        score = base_score + (triple_bonus if data.stars == 3 and allow_triple_bonus else 0)

    if data.is_too_low_violation and not data.is_above_self_violation:
        excess = data.defender_position - (data.attacker_position + 10)
        penalty_base = 8 + 2 * max(excess, 0)
        score = -2 * penalty_base if data.stars == 3 else -4 * penalty_base

    return ContributionResult(score=round(max(score, -40), 2))


def calculate_unused_attack_penalty(*, is_cwl: bool, unused_attacks: int, attacker_position: int, opponent_positions: list[int], attacked_defender_positions: list[int]) -> float:
    if is_cwl or unused_attacks <= 0:
        return 0.0
    attackable = {p for p in opponent_positions if attacker_position <= p <= attacker_position + 10}
    if not attackable:
        return 0.0
    unattacked_global = set(opponent_positions) - set(attacked_defender_positions)
    if not unattacked_global:
        return 0.0
    useful_unattacked = attackable & unattacked_global
    if unused_attacks >= 2 and len(useful_unattacked) >= 2:
        return -30.0
    if unused_attacks >= 1 and len(useful_unattacked) >= 1:
        return -12.0
    return 0.0


def calculate_cwl_unused_attack_penalty(*, unused_attack: bool, opponent_positions: list[int], attacked_defender_positions: list[int]) -> float:
    if not unused_attack:
        return 0.0
    unattacked_global = set(opponent_positions) - set(attacked_defender_positions)
    return -40.0 if unattacked_global else 0.0


def calculate_player_contribution(data: ContributionPlayerInput) -> ContributionResult:
    total = sum(calculate_attack_contribution(attack).score for attack in data.attacks)
    total += calculate_unused_attack_penalty(
        is_cwl=data.is_cwl,
        unused_attacks=data.unused_attacks,
        attacker_position=data.attacker_position,
        opponent_positions=data.opponent_positions,
        attacked_defender_positions=data.attacked_defender_positions,
    )
    return ContributionResult(score=round(total, 2))

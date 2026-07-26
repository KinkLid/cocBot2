from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.violation_rules import (
    evaluate_attack_violation,
    resolve_allowed_targets_for_attack,
)
from app.models.enums import ViolationCode


@dataclass(frozen=True)
class AttackResult:
    defender_position: int
    stars: int
    destruction: float
    observed_at: datetime


def test_feliks_second_attack_allows_nearest_untripled_target() -> None:
    start = datetime(2026, 7, 19, 0, 28, 10, tzinfo=UTC)
    first_attack_at = datetime(2026, 7, 19, 9, 56, 5, tzinfo=UTC)
    second_attack_at = datetime(2026, 7, 19, 9, 59, 5, tzinfo=UTC)

    previous_attacks = [
        AttackResult(8, 3, 100, start + timedelta(hours=7, minutes=37)),
        AttackResult(9, 3, 100, first_attack_at),
        AttackResult(11, 3, 100, start + timedelta(hours=8, minutes=46)),
        AttackResult(12, 3, 100, start + timedelta(hours=8, minutes=40)),
        AttackResult(13, 3, 100, start + timedelta(hours=8, minutes=10)),
        AttackResult(14, 3, 100, start + timedelta(hours=6, minutes=56)),
        AttackResult(15, 3, 100, start + timedelta(hours=8, minutes=7)),
    ]

    allowed_targets = resolve_allowed_targets_for_attack(
        war_start_time=start,
        attack_seen_at=second_attack_at,
        attacker_position=13,
        defender_positions=range(1, 41),
        allied_attacks=previous_attacks,
    )
    decision = evaluate_attack_violation(
        war_start_time=start,
        attack_seen_at=second_attack_at,
        attacker_position=13,
        defender_position=10,
        defender_positions=range(1, 41),
        allied_attacks=previous_attacks,
    )

    assert allowed_targets.positions == frozenset({10})
    assert decision.violated is False


def test_feliks_first_attack_is_still_above_self_violation() -> None:
    start = datetime(2026, 7, 19, 0, 28, 10, tzinfo=UTC)
    attack_seen_at = datetime(2026, 7, 19, 9, 56, 5, tzinfo=UTC)

    previous_attacks = [
        AttackResult(8, 3, 100, start + timedelta(hours=7, minutes=37)),
        AttackResult(11, 3, 100, start + timedelta(hours=8, minutes=46)),
        AttackResult(12, 3, 100, start + timedelta(hours=8, minutes=40)),
        AttackResult(13, 3, 100, start + timedelta(hours=8, minutes=10)),
        AttackResult(14, 3, 100, start + timedelta(hours=6, minutes=56)),
        AttackResult(15, 3, 100, start + timedelta(hours=8, minutes=7)),
    ]

    decision = evaluate_attack_violation(
        war_start_time=start,
        attack_seen_at=attack_seen_at,
        attacker_position=13,
        defender_position=9,
        defender_positions=range(1, 41),
        allied_attacks=previous_attacks,
    )

    assert decision.violated is True
    assert decision.code == ViolationCode.ABOVE_SELF


def test_equal_nearest_targets_on_both_sides_are_both_allowed() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    tripled = [
        AttackResult(position, 3, 100, start + timedelta(hours=1))
        for position in range(9, 14)
    ]
    tripled.extend(
        [
            AttackResult(8, 3, 100, start + timedelta(hours=1)),
            AttackResult(14, 3, 100, start + timedelta(hours=1)),
        ]
    )

    allowed_targets = resolve_allowed_targets_for_attack(
        war_start_time=start,
        attack_seen_at=seen_at,
        attacker_position=10,
        defender_positions=range(1, 21),
        allied_attacks=tripled,
    )

    assert allowed_targets.positions == frozenset({7, 15})

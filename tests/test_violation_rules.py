from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.violation_rules import evaluate_attack_violation
from app.models.enums import ViolationCode


def test_evaluate_attack_violation_handles_naive_war_start_and_aware_attack_time() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0)
    attack_seen_at = datetime(2026, 4, 1, 11, 0, tzinfo=UTC)

    decision = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=12,
        defender_position=5,
    )

    assert decision.violated is True
    assert decision.code == ViolationCode.ABOVE_SELF


def test_evaluate_attack_violation_handles_aware_war_start_and_naive_attack_time() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    attack_seen_at = datetime(2026, 4, 1, 11, 0)

    decision = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=12,
        defender_position=23,
    )

    assert decision.violated is True
    assert decision.code == ViolationCode.TOO_LOW


def test_evaluate_attack_violation_handles_both_aware_datetimes() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    attack_seen_at = datetime(2026, 4, 1, 11, 0, tzinfo=UTC)

    decision = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=12,
        defender_position=22,
    )

    assert decision.violated is False


def test_attack_after_12_hours_is_not_a_violation_for_mixed_datetime_types() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0)
    attack_seen_at = datetime(2026, 4, 1, 23, 0, tzinfo=UTC)

    decision = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=20,
        defender_position=1,
    )

    assert decision.violated is False


def test_first_12_hours_rules_are_preserved_without_regression() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    attack_seen_at = war_start_time + timedelta(hours=2)

    mirror = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=26,
        defender_position=26,
    )
    above_self = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=26,
        defender_position=25,
    )
    allowed_low = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=26,
        defender_position=36,
    )
    too_low = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=26,
        defender_position=37,
    )

    assert mirror.violated is False
    assert above_self.violated is True and above_self.code == ViolationCode.ABOVE_SELF
    assert allowed_low.violated is False
    assert too_low.violated is True and too_low.code == ViolationCode.TOO_LOW

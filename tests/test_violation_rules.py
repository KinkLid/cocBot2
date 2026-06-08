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
        defender_position=15,
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


def test_regular_war_position_boundaries_in_first_12_hours() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    attack_seen_at = war_start_time + timedelta(hours=2)

    cases = [
        (10, 9, False, None),
        (10, 8, True, ViolationCode.ABOVE_SELF),
        (10, 13, False, None),
        (10, 14, True, ViolationCode.TOO_LOW),
    ]
    for attacker, defender, violated, code in cases:
        decision = evaluate_attack_violation(
            war_start_time=war_start_time,
            attack_seen_at=attack_seen_at,
            attacker_position=attacker,
            defender_position=defender,
        )
        assert decision.violated is violated
        assert decision.code == code


def test_updated_violation_reason_texts() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    above = evaluate_attack_violation(start, start + timedelta(hours=1), 10, 8)
    low = evaluate_attack_violation(start, start + timedelta(hours=1), 10, 14)

    assert above.reason_text == (
        "Атака по сопернику выше своей позиции более чем на 1 место в первые 12 часов"
    )
    assert low.reason_text == (
        "Атака по сопернику ниже своей позиции более чем на 3 места в первые 12 часов"
    )

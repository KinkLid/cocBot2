from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.violation_rules import (
    best_previous_results_by_defender,
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


def make_results(
    positions: range | list[int],
    observed_at: datetime,
    *,
    stars: int = 3,
    destruction: float = 100,
) -> list[AttackResult]:
    return [
        AttackResult(position, stars, destruction, observed_at)
        for position in positions
    ]


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


def test_attack_after_12_hours_is_not_a_violation() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0)
    attack_seen_at = datetime(2026, 4, 1, 22, 0, 1, tzinfo=UTC)

    decision = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=20,
        defender_position=1,
        defender_positions=range(1, 31),
    )

    assert decision.violated is False


def test_attack_at_exactly_12_hours_is_still_checked() -> None:
    war_start_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    decision = evaluate_attack_violation(
        war_start_time=war_start_time,
        attack_seen_at=war_start_time + timedelta(hours=12),
        attacker_position=20,
        defender_position=1,
        defender_positions=range(1, 31),
    )

    assert decision.violated is True
    assert decision.code == ViolationCode.ABOVE_SELF


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
            defender_positions=range(1, 21),
        )
        assert decision.violated is violated
        assert decision.code == code


def test_outside_base_window_is_violation_while_base_target_is_not_tripled() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results([9, 10, 11, 12], start + timedelta(hours=1))

    decision = evaluate_attack_violation(
        start,
        seen_at,
        10,
        14,
        range(1, 21),
        attacks,
    )

    assert decision.violated is True
    assert decision.code == ViolationCode.TOO_LOW


def test_nearest_below_is_only_fallback_when_base_window_is_tripled() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results(range(9, 14), start + timedelta(hours=1))

    allowed = evaluate_attack_violation(
        start, seen_at, 10, 14, range(1, 21), attacks
    )
    skipped = evaluate_attack_violation(
        start, seen_at, 10, 15, range(1, 21), attacks
    )

    assert allowed.violated is False
    assert skipped.violated is True
    assert skipped.code == ViolationCode.TOO_LOW


def test_nearest_above_is_fallback_when_base_and_lower_targets_are_tripled() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results(range(9, 21), start + timedelta(hours=1))

    allowed_targets = resolve_allowed_targets_for_attack(
        start,
        seen_at,
        10,
        range(1, 21),
        attacks,
    )
    allowed = evaluate_attack_violation(
        start, seen_at, 10, 8, range(1, 21), attacks
    )
    skipped = evaluate_attack_violation(
        start, seen_at, 10, 7, range(1, 21), attacks
    )

    assert allowed_targets.positions == frozenset({8})
    assert allowed.violated is False
    assert skipped.violated is True
    assert skipped.code == ViolationCode.ABOVE_SELF


def test_all_targets_tripled_allows_any_target() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results(range(1, 21), start + timedelta(hours=1))

    decision = evaluate_attack_violation(
        start, seen_at, 10, 1, range(1, 21), attacks
    )

    assert decision.violated is False


def test_future_attacks_do_not_open_fallback_but_previous_attacks_do() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    future_triples = make_results(range(9, 14), seen_at + timedelta(minutes=1))
    previous_triples = make_results(range(9, 14), seen_at - timedelta(minutes=1))

    before_future_attacks = evaluate_attack_violation(
        start, seen_at, 10, 14, range(1, 21), future_triples
    )
    after_previous_attacks = evaluate_attack_violation(
        start, seen_at, 10, 14, range(1, 21), previous_triples
    )

    assert before_future_attacks.violated is True
    assert after_previous_attacks.violated is False


def test_best_previous_result_uses_stars_then_destruction() -> None:
    seen_at = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    attacks = [
        AttackResult(10, 2, 99, seen_at - timedelta(minutes=4)),
        AttackResult(10, 3, 50, seen_at - timedelta(minutes=3)),
        AttackResult(10, 3, 70, seen_at - timedelta(minutes=2)),
        AttackResult(10, 3, 100, seen_at + timedelta(minutes=1)),
    ]

    best = best_previous_results_by_defender(seen_at, attacks)

    assert best[10].stars == 3
    assert best[10].destruction == 70


def test_cwl_allows_any_target() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    decision = evaluate_attack_violation(
        start,
        start + timedelta(hours=1),
        10,
        1,
        range(1, 21),
        is_cwl=True,
    )

    assert decision.violated is False


def test_updated_violation_reason_texts() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    above = evaluate_attack_violation(
        start, start + timedelta(hours=1), 10, 8, range(1, 21)
    )
    low = evaluate_attack_violation(
        start, start + timedelta(hours=1), 10, 14, range(1, 21)
    )

    assert above.reason_text == (
        "Атака по сопернику выше разрешенной позиции в первые 12 часов"
    )
    assert low.reason_text == (
        "Атака по сопернику ниже разрешенной позиции в первые 12 часов"
    )


def test_bottom_edge_position_49_falls_back_above_without_phantom_targets() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results([48, 49, 50], seen_at - timedelta(minutes=1))

    allowed_targets = resolve_allowed_targets_for_attack(
        start, seen_at, 49, range(1, 51), attacks
    )
    decision = evaluate_attack_violation(
        start, seen_at, 49, 47, range(1, 51), attacks
    )

    assert allowed_targets.positions == frozenset({47})
    assert all(position <= 50 for position in allowed_targets.positions)
    assert 51 not in allowed_targets.positions
    assert 52 not in allowed_targets.positions
    assert decision.violated is False


def test_bottom_edge_position_50_falls_back_to_nearest_above() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results([49, 50], seen_at - timedelta(minutes=1))

    allowed_targets = resolve_allowed_targets_for_attack(
        start, seen_at, 50, range(1, 51), attacks
    )
    decision = evaluate_attack_violation(
        start, seen_at, 50, 48, range(1, 51), attacks
    )

    assert allowed_targets.positions == frozenset({48})
    assert decision.violated is False


def test_top_edge_position_1_falls_back_to_nearest_below() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results([1, 2, 3, 4], seen_at - timedelta(minutes=1))

    allowed_targets = resolve_allowed_targets_for_attack(
        start, seen_at, 1, range(1, 51), attacks
    )
    decision = evaluate_attack_violation(
        start, seen_at, 1, 5, range(1, 51), attacks
    )

    assert allowed_targets.positions == frozenset({5})
    assert decision.violated is False


def test_25v25_allowed_targets_never_exceed_roster_positions() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results([24, 25], seen_at - timedelta(minutes=1))

    allowed_targets = resolve_allowed_targets_for_attack(
        start, seen_at, 25, range(1, 26), attacks
    )

    assert allowed_targets.allow_any is False
    assert allowed_targets.positions
    assert max(allowed_targets.positions) <= 25


def test_all_real_targets_tripled_sets_allow_any() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results(range(1, 51), seen_at - timedelta(minutes=1))

    allowed_targets = resolve_allowed_targets_for_attack(
        start, seen_at, 49, range(1, 51), attacks
    )
    decision = evaluate_attack_violation(
        start, seen_at, 49, 1, range(1, 51), attacks
    )

    assert allowed_targets.allow_any is True
    assert decision.violated is False


def test_base_window_open_target_prevents_fallback() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results([48, 50], seen_at - timedelta(minutes=1))

    allowed_targets = resolve_allowed_targets_for_attack(
        start, seen_at, 49, range(1, 51), attacks
    )
    decision = evaluate_attack_violation(
        start, seen_at, 49, 47, range(1, 51), attacks
    )

    assert allowed_targets.positions == frozenset({48, 49, 50})
    assert decision.violated is True
    assert decision.code == ViolationCode.ABOVE_SELF

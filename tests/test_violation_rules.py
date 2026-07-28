from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.violation_rules import (
    best_previous_results_by_defender,
    evaluate_attack_violation,
    evaluate_war_attack_violations,
    resolve_allowed_targets_for_attack,
)
from app.models.enums import ViolationCode


@dataclass(frozen=True)
class AttackResult:
    defender_position: int
    stars: int
    destruction: float
    observed_at: datetime


@dataclass(frozen=True)
class WarAttackResult:
    id: int
    attacker_tag: str
    attacker_position: int
    defender_position: int
    stars: int
    destruction: float
    observed_at: datetime
    attack_order: int | None = None


def test_war_order_wins_when_api_member_iteration_is_reversed() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    base = [
        WarAttackResult(order, f"#ALLY{target}", target, target, 3, 100, start, order)
        for order, target in enumerate(range(11, 17), 1)
    ]
    closed_ten = WarAttackResult(7, "#ALLY", 10, 10, 3, 100, start, 7)
    hit_nine = WarAttackResult(8, "#FELIKS", 13, 9, 3, 100, start, 8)

    decisions = evaluate_war_attack_violations(
        start, range(1, 31), [hit_nine, closed_ten, *base], attacks_per_member=2
    )

    assert decisions[hit_nine.id].violated is False


def test_later_ally_attack_does_not_retroactively_allow_earlier_hit() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    base = [
        WarAttackResult(order, f"#ALLY{target}", target, target, 3, 100, start, order)
        for order, target in enumerate(range(11, 17), 1)
    ]
    hit_nine = WarAttackResult(7, "#FELIKS", 13, 9, 3, 100, start, 7)
    late_ten = WarAttackResult(8, "#ALLY", 10, 10, 3, 100, start, 8)

    decisions = evaluate_war_attack_violations(
        start, range(1, 31), [late_ten, hit_nine, *base], attacks_per_member=1
    )

    assert decisions[hit_nine.id].violated is True


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


def test_nearest_open_target_is_fallback_when_base_window_is_tripled() -> None:
    start = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    seen_at = start + timedelta(hours=2)
    attacks = make_results(range(9, 14), start + timedelta(hours=1))

    allowed = evaluate_attack_violation(start, seen_at, 10, 8, range(1, 21), attacks)
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
        start, seen_at, 10, 8, range(1, 21), previous_triples
    )

    assert before_future_attacks.violated is True
    assert after_previous_attacks.violated is False


def test_feliks_fallback_uses_distance_and_only_previous_attacks() -> None:
    start = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
    first_seen = datetime(2026, 7, 19, 9, 56, tzinfo=UTC)
    base_triples = make_results(
        [position for position in range(1, 31) if position not in {9, 10}],
        first_seen - timedelta(minutes=1),
    )

    attack_nine = evaluate_attack_violation(
        start, first_seen, 13, 9, range(1, 31), base_triples
    )
    nine_tripled = AttackResult(9, 3, 100, first_seen)
    attack_ten = evaluate_attack_violation(
        start,
        first_seen + timedelta(minutes=3),
        13,
        10,
        range(1, 31),
        [*base_triples, nine_tripled],
    )

    assert attack_nine.violated is True
    assert attack_nine.code == ViolationCode.ABOVE_SELF
    assert attack_ten.violated is False


def test_equally_near_open_targets_on_both_sides_are_allowed() -> None:
    start = datetime(2026, 4, 1, 10, tzinfo=UTC)
    seen = start + timedelta(hours=1)
    triples = make_results(
        [position for position in range(1, 21) if position not in {6, 14}],
        seen - timedelta(minutes=1),
    )

    targets = resolve_allowed_targets_for_attack(start, seen, 10, range(1, 21), triples)

    assert targets.positions == frozenset({6, 14})


def test_one_or_two_star_target_in_base_window_prevents_fallback() -> None:
    start = datetime(2026, 4, 1, 10, tzinfo=UTC)
    seen = start + timedelta(hours=1)
    attacks = make_results([9, 10, 12, 13], seen - timedelta(minutes=2))
    attacks.append(AttackResult(11, 2, 99, seen - timedelta(minutes=1)))

    decision = evaluate_attack_violation(start, seen, 10, 8, range(1, 21), attacks)

    assert decision.violated is True


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


def _sequence(*targets: tuple[int, int], attacker=13, roster_size=30):
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    attacks = [
        WarAttackResult(index, f"#ALLY{target}", target, target, 3, 100, start)
        for index, target in enumerate([11, 12, 13, 14, 15, 16], 1)
    ]
    attacks.extend(
        WarAttackResult(100 + index, "#F", attacker, target, stars, 100,
                        start + timedelta(hours=1))
        for index, (target, stars) in enumerate(targets)
    )
    return evaluate_war_attack_violations(start, range(1, roster_size + 1), attacks)


def test_feliks_reverse_order_is_retroactively_allowed() -> None:
    decisions = _sequence((9, 3), (10, 3))
    assert decisions[100].violated is False
    assert decisions[101].violated is False


def test_feliks_gap_that_is_not_tripled_keeps_far_attack_violation() -> None:
    decisions = _sequence((9, 3), (10, 2))
    assert decisions[100].code == ViolationCode.ABOVE_SELF
    assert decisions[101].violated is False


def test_three_target_chain_and_independent_sides() -> None:
    complete = _sequence((8, 3), (10, 3), (9, 3), (17, 3))
    assert all(not complete[attack_id].violated for attack_id in range(100, 104))

    gap = _sequence((8, 3), (10, 3), (9, 2), (17, 3))
    assert gap[100].code == ViolationCode.ABOVE_SELF
    assert gap[103].violated is False


def test_reverse_lower_chain_requires_continuous_triples() -> None:
    complete = _sequence((18, 3), (17, 3))
    assert not complete[100].violated and not complete[101].violated
    gap = _sequence((18, 3), (17, 2))
    assert gap[100].code == ViolationCode.TOO_LOW
    assert not gap[101].violated


@pytest.mark.parametrize("targets", [
    ((9, 2), (10, 3), (8, 3)),
    ((10, 3), (9, 2), (8, 3)),
])
def test_open_above_boundary_is_allowed_but_does_not_open_next_target(targets) -> None:
    decisions = _sequence(*targets)

    assert decisions[100].violated is False
    assert decisions[101].violated is False
    assert decisions[102].code == ViolationCode.ABOVE_SELF


@pytest.mark.parametrize("targets", [
    ((18, 2), (17, 3), (19, 3)),
    ((17, 3), (18, 2), (19, 3)),
])
def test_open_lower_boundary_is_allowed_but_does_not_open_next_target(targets) -> None:
    decisions = _sequence(*targets)

    assert decisions[100].violated is False
    assert decisions[101].violated is False
    assert decisions[102].code == ViolationCode.TOO_LOW


def _base_transition(*player_targets, ally_between=None):
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    attacks = [
        WarAttackResult(index, f"#ALLY{target}", target, target, 3, 100, start)
        for index, target in enumerate([12, 13, 14, 15], 1)
    ]
    attacks.append(
        WarAttackResult(100, "#F", 13, player_targets[0][0], player_targets[0][1], 100,
                        start + timedelta(hours=1))
    )
    if ally_between is not None:
        attacks.append(
            WarAttackResult(101, "#ALLY", 16, 16, ally_between, 100,
                            start + timedelta(hours=1, seconds=1))
        )
    attacks.append(
        WarAttackResult(102, "#F", 13, player_targets[1][0], player_targets[1][1], 100,
                        start + timedelta(hours=1, seconds=2))
    )
    return evaluate_war_attack_violations(start, range(1, 31), attacks)


def test_player_closing_last_base_target_opens_external_boundary() -> None:
    decisions = _base_transition((16, 3), (17, 2))
    assert not decisions[100].violated
    assert not decisions[102].violated


def test_two_stars_on_last_base_target_does_not_open_boundary() -> None:
    decisions = _base_transition((16, 2), (17, 3))
    assert not decisions[100].violated
    assert decisions[102].code == ViolationCode.TOO_LOW


def test_external_attack_before_base_closure_stays_a_violation() -> None:
    decisions = _base_transition((17, 3), (16, 3))
    assert decisions[100].code == ViolationCode.TOO_LOW
    assert not decisions[102].violated


def test_ally_closing_last_base_target_between_attacks_opens_boundary() -> None:
    decisions = _base_transition((15, 2), (17, 2), ally_between=3)
    assert not decisions[100].violated
    assert not decisions[102].violated


def test_ally_moves_external_boundary_between_player_attacks() -> None:
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    attacks = [
        WarAttackResult(i, f"#A{target}", target, target, 3, 100, start)
        for i, target in enumerate(range(11, 17), 1)
    ]
    attacks.extend([
        WarAttackResult(100, "#F", 13, 10, 2, 80, start + timedelta(hours=1)),
        WarAttackResult(101, "#ALLY", 20, 10, 3, 100,
                        start + timedelta(hours=1, seconds=1)),
        WarAttackResult(102, "#F", 13, 9, 2, 80,
                        start + timedelta(hours=1, seconds=2)),
    ])

    decisions = evaluate_war_attack_violations(start, range(1, 31), attacks)

    assert not decisions[100].violated
    assert not decisions[102].violated


def test_late_ally_triple_does_not_retroactively_move_boundary() -> None:
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    attacks = [
        WarAttackResult(i, f"#A{target}", target, target, 3, 100, start)
        for i, target in enumerate(range(11, 17), 1)
    ]
    attacks.extend([
        WarAttackResult(100, "#F", 13, 9, 3, 100, start + timedelta(hours=1)),
        WarAttackResult(101, "#ALLY", 20, 10, 3, 100,
                        start + timedelta(hours=1, seconds=1)),
    ])

    decision = evaluate_war_attack_violations(
        start, range(1, 31), attacks, attacks_per_member=1
    )[100]

    assert decision.code == ViolationCode.ABOVE_SELF
    assert decision.is_final is True


def test_fixable_external_jump_is_pending_until_sequence_finishes() -> None:
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    attacks = [
        WarAttackResult(i, f"#A{target}", target, target, 3, 100, start)
        for i, target in enumerate(range(11, 17), 1)
    ]
    attacks.append(
        WarAttackResult(100, "#F", 13, 9, 3, 100, start + timedelta(hours=1))
    )

    decision = evaluate_war_attack_violations(
        start, range(1, 31), attacks, attacks_per_member=2,
        evaluated_at=start + timedelta(hours=2),
    )[100]

    assert decision.code == ViolationCode.ABOVE_SELF
    assert decision.is_final is False


@pytest.mark.parametrize("roster_size,attacker,targets", [
    (15, 1, ((5, 3),)),
    (30, 30, ((27, 3),)),
])
def test_sequence_uses_only_real_roster_edges(roster_size, attacker, targets) -> None:
    decisions = _sequence(*targets, attacker=attacker, roster_size=roster_size)
    assert set(decisions) and all(isinstance(item.violated, bool) for item in decisions.values())

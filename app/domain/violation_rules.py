from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Protocol

from app.models.enums import ViolationCode
from app.utils.time import normalize_utc


@dataclass(slots=True)
class ViolationDecision:
    violated: bool
    code: ViolationCode | None = None
    reason_text: str | None = None


@dataclass(frozen=True, slots=True)
class PreviousAttackResult:
    defender_position: int
    stars: int
    destruction: float


@dataclass(frozen=True, slots=True)
class AllowedTargets:
    positions: frozenset[int] = frozenset()
    allow_any: bool = False


class AttackResult(Protocol):
    id: int
    attacker_tag: str
    attacker_position: int
    defender_position: int
    stars: int
    destruction: float
    observed_at: datetime


TWELVE_HOURS = timedelta(hours=12)


def attack_order_key(attack: AttackResult) -> tuple[datetime, int]:
    """Return the single stable ordering used by every reconciliation path."""
    return normalize_utc(attack.observed_at), attack.id


def evaluate_war_attack_violations(
    war_start_time: datetime | None,
    defender_positions: Iterable[int],
    attacks: Iterable[AttackResult],
    *,
    is_cwl: bool = False,
) -> dict[int, ViolationDecision]:
    """Calculate final positional decisions, including retrospective chains.

    The calculation is deliberately pure.  Persistence and notifications are
    handled by callers, so live sync and historical recalculation cannot drift.
    """
    ordered = sorted(attacks, key=attack_order_key)
    roster = sorted(set(defender_positions))
    decisions: dict[int, ViolationDecision] = {}

    if war_start_time is None or is_cwl:
        return {attack.id: ViolationDecision(False) for attack in ordered}

    start = normalize_utc(war_start_time)
    in_window = [
        attack
        for attack in ordered
        if normalize_utc(attack.observed_at) <= start + TWELVE_HOURS
    ]
    in_window_ids = {attack.id for attack in in_window}
    for attack in ordered:
        if attack.id not in in_window_ids:
            decisions[attack.id] = ViolationDecision(False)

    triples_before: dict[int, frozenset[int]] = {}
    tripled: set[int] = set()
    for attack in in_window:
        triples_before[attack.id] = frozenset(tripled)
        if attack.stars == 3:
            tripled.add(attack.defender_position)

    by_player: dict[str, list[AttackResult]] = {}
    for attack in in_window:
        by_player.setdefault(attack.attacker_tag, []).append(attack)

    for player_attacks in by_player.values():
        position = player_attacks[0].attacker_position
        base = [target for target in roster if position - 1 <= target <= position + 3]
        external_attacks: list[AttackResult] = []
        for attack in player_attacks:
            if attack.defender_position in base:
                decisions[attack.id] = ViolationDecision(False)
            elif base and all(
                target in triples_before[attack.id] for target in base
            ):
                external_attacks.append(attack)
            else:
                # Crossing the boundary before the base is closed remains a
                # violation even if a later attack completes the base.
                decisions[attack.id] = _decision_for_positions(
                    attack.attacker_position,
                    attack.defender_position,
                    frozenset(base),
                )

        if not external_attacks:
            continue

        baseline_tripled = set(triples_before[external_attacks[0].id])
        above = [target for target in reversed(roster) if target < position - 1]
        below = [target for target in roster if target > position + 3]

        allowed_external: set[int] = set()
        for chain in (above, below):
            required = [target for target in chain if target not in baseline_tripled]
            if not required:
                continue
            player_triples = {
                attack.defender_position
                for attack in external_attacks
                if attack.stars == 3
            }
            # The nearest still-open target is legal even when it is not
            # tripled. More distant targets become legal only through the
            # final, continuously tripled prefix.
            for target in required:
                allowed_external.add(target)
                if target not in player_triples:
                    break

        for attack in external_attacks:
            if attack.defender_position in baseline_tripled:
                decisions[attack.id] = ViolationDecision(False)
            else:
                decisions[attack.id] = _decision_for_positions(
                    attack.attacker_position,
                    attack.defender_position,
                    frozenset(allowed_external),
                )

    return decisions


def _decision_for_positions(
    attacker_position: int,
    defender_position: int,
    allowed: frozenset[int],
) -> ViolationDecision:
    if defender_position in allowed:
        return ViolationDecision(False)
    code = (
        ViolationCode.ABOVE_SELF
        if defender_position < attacker_position
        else ViolationCode.TOO_LOW
    )
    direction = "выше" if code == ViolationCode.ABOVE_SELF else "ниже"
    return ViolationDecision(
        True,
        code,
        f"Атака по сопернику {direction} разрешенной позиции в первые 12 часов",
    )


def best_previous_results_by_defender(
    current_attack_seen_at: datetime,
    allied_attacks: Iterable[AttackResult],
    current_attack_id: int | None = None,
) -> dict[int, PreviousAttackResult]:
    current_seen_at = normalize_utc(current_attack_seen_at)
    best_results: dict[int, PreviousAttackResult] = {}

    for attack in allied_attacks:
        attack_seen_at = normalize_utc(attack.observed_at)
        attack_id = getattr(attack, "id", None)
        is_previous = attack_seen_at < current_seen_at or (
            current_attack_id is not None
            and attack_id is not None
            and (attack_seen_at, attack_id) < (current_seen_at, current_attack_id)
        )
        if not is_previous:
            continue

        result = PreviousAttackResult(
            defender_position=attack.defender_position,
            stars=attack.stars,
            destruction=attack.destruction,
        )
        previous_best = best_results.get(result.defender_position)
        if previous_best is None or (result.stars, result.destruction) > (
            previous_best.stars,
            previous_best.destruction,
        ):
            best_results[result.defender_position] = result

    return best_results


def resolve_allowed_targets_for_attack(
    war_start_time: datetime | None,
    attack_seen_at: datetime,
    attacker_position: int,
    defender_positions: Iterable[int],
    allied_attacks: Iterable[AttackResult] = (),
    *,
    is_cwl: bool = False,
    current_attack_id: int | None = None,
) -> AllowedTargets:
    if war_start_time is None or is_cwl:
        return AllowedTargets(allow_any=True)

    normalized_war_start_time = normalize_utc(war_start_time)
    normalized_attack_seen_at = normalize_utc(attack_seen_at)
    if normalized_attack_seen_at > normalized_war_start_time + TWELVE_HOURS:
        return AllowedTargets(allow_any=True)

    roster_positions = sorted(set(defender_positions))
    best_results = best_previous_results_by_defender(
        attack_seen_at, allied_attacks, current_attack_id
    )

    def is_tripled(position: int) -> bool:
        result = best_results.get(position)
        return result is not None and result.stars == 3

    base_min_position = attacker_position - 1
    base_max_position = attacker_position + 3
    base_positions = [
        position
        for position in roster_positions
        if base_min_position <= position <= base_max_position
    ]
    if any(not is_tripled(position) for position in base_positions):
        return AllowedTargets(positions=frozenset(base_positions))

    open_positions = [position for position in roster_positions if not is_tripled(position)]
    if open_positions:
        nearest_distance = min(
            abs(position - attacker_position) for position in open_positions
        )
        return AllowedTargets(
            positions=frozenset(
                position
                for position in open_positions
                if abs(position - attacker_position) == nearest_distance
            )
        )

    return AllowedTargets(allow_any=True)


def evaluate_attack_violation(
    war_start_time: datetime | None,
    attack_seen_at: datetime,
    attacker_position: int,
    defender_position: int,
    defender_positions: Iterable[int] | None = None,
    allied_attacks: Iterable[AttackResult] = (),
    *,
    is_cwl: bool = False,
    current_attack_id: int | None = None,
) -> ViolationDecision:
    roster_positions = defender_positions
    if roster_positions is None:
        roster_positions = range(
            max(1, attacker_position - 1),
            max(attacker_position + 3, defender_position) + 1,
        )

    allowed_targets = resolve_allowed_targets_for_attack(
        war_start_time=war_start_time,
        attack_seen_at=attack_seen_at,
        attacker_position=attacker_position,
        defender_positions=roster_positions,
        allied_attacks=allied_attacks,
        is_cwl=is_cwl,
        current_attack_id=current_attack_id,
    )
    if allowed_targets.allow_any or defender_position in allowed_targets.positions:
        return ViolationDecision(violated=False)

    if allowed_targets.positions:
        allowed_position = min(allowed_targets.positions)
        if defender_position > max(allowed_targets.positions):
            code = ViolationCode.TOO_LOW
            reason_text = "Атака по сопернику ниже разрешенной позиции в первые 12 часов"
        elif defender_position < allowed_position:
            code = ViolationCode.ABOVE_SELF
            reason_text = "Атака по сопернику выше разрешенной позиции в первые 12 часов"
        else:
            code = (
                ViolationCode.ABOVE_SELF
                if defender_position < attacker_position
                else ViolationCode.TOO_LOW
            )
            reason_text = (
                "Атака по сопернику выше разрешенной позиции в первые 12 часов"
                if code == ViolationCode.ABOVE_SELF
                else "Атака по сопернику ниже разрешенной позиции в первые 12 часов"
            )
        return ViolationDecision(violated=True, code=code, reason_text=reason_text)

    return ViolationDecision(violated=False)

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable, Protocol

from app.models.enums import ViolationCode


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
    defender_position: int
    stars: int
    destruction: float
    observed_at: datetime


TWELVE_HOURS = timedelta(hours=12)


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def best_previous_results_by_defender(
    current_attack_seen_at: datetime,
    allied_attacks: Iterable[AttackResult],
) -> dict[int, PreviousAttackResult]:
    current_seen_at = _normalize_utc(current_attack_seen_at)
    best_results: dict[int, PreviousAttackResult] = {}

    for attack in allied_attacks:
        if _normalize_utc(attack.observed_at) >= current_seen_at:
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
) -> AllowedTargets:
    if war_start_time is None or is_cwl:
        return AllowedTargets(allow_any=True)

    normalized_war_start_time = _normalize_utc(war_start_time)
    normalized_attack_seen_at = _normalize_utc(attack_seen_at)
    if normalized_attack_seen_at > normalized_war_start_time + TWELVE_HOURS:
        return AllowedTargets(allow_any=True)

    roster_positions = sorted(set(defender_positions))
    best_results = best_previous_results_by_defender(attack_seen_at, allied_attacks)

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

    nearest_below = next(
        (
            position
            for position in roster_positions
            if position > base_max_position and not is_tripled(position)
        ),
        None,
    )
    if nearest_below is not None:
        return AllowedTargets(positions=frozenset({nearest_below}))

    nearest_above = next(
        (
            position
            for position in reversed(roster_positions)
            if position < base_min_position and not is_tripled(position)
        ),
        None,
    )
    if nearest_above is not None:
        return AllowedTargets(positions=frozenset({nearest_above}))

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

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.enums import ViolationCode


@dataclass(slots=True)
class ViolationDecision:
    violated: bool
    code: ViolationCode | None = None
    reason_text: str | None = None


TWELVE_HOURS = timedelta(hours=12)


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def evaluate_attack_violation(
    war_start_time: datetime | None,
    attack_seen_at: datetime,
    attacker_position: int,
    defender_position: int,
) -> ViolationDecision:
    if war_start_time is None:
        return ViolationDecision(violated=False)

    normalized_war_start_time = _normalize_utc(war_start_time)
    normalized_attack_seen_at = _normalize_utc(attack_seen_at)

    if normalized_attack_seen_at >= normalized_war_start_time + TWELVE_HOURS:
        return ViolationDecision(violated=False)

    min_allowed_position = attacker_position
    max_allowed_position = attacker_position + 10

    if defender_position < min_allowed_position:
        return ViolationDecision(
            violated=True,
            code=ViolationCode.ABOVE_SELF,
            reason_text="Атака по сопернику выше своей позиции в первые 12 часов",
        )

    if defender_position > max_allowed_position:
        return ViolationDecision(
            violated=True,
            code=ViolationCode.TOO_LOW,
            reason_text="Атака по сопернику ниже своей позиции более чем на 10 мест в первые 12 часов",
        )

    return ViolationDecision(violated=False)

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.violation_rules import attack_order_key, evaluate_war_attack_violations
from app.models import Violation
from app.models.enums import ViolationCode, WarState, WarType
from app.repositories.war import WarRepository
from app.services.period import PeriodService
from app.utils.time import normalize_utc, utcnow


POSITIONAL_CODES = {ViolationCode.ABOVE_SELF, ViolationCode.TOO_LOW}


class IncompleteWarRosterError(ValueError):
    """Raised before mutation when a saved enemy roster cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ViolationRecalculationResult:
    wars_processed: int = 0
    attacks_checked: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    created_attack_ids: tuple[int, ...] = ()
    pending: int = 0


class ViolationRecalculationService:
    """Reconcile saved automatic positional violations without API calls or notices."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.wars = WarRepository(session)
        self.periods = PeriodService(session)

    async def recalculate_current_cycle(self) -> ViolationRecalculationResult:
        period = await self.periods.current_cycle()
        wars = await self.wars.list_regular_wars_in_period(period.start, period.end)
        created = updated = deleted = unchanged = attacks_checked = pending = 0
        created_attack_ids: list[int] = []

        for war in wars:
            defender_positions = sorted(
                participant.map_position
                for participant in war.participants
                if not participant.is_own_clan
            )
            if (
                not defender_positions
                or len(defender_positions) != len(set(defender_positions))
                or len(set(defender_positions)) != war.team_size
            ):
                raise IncompleteWarRosterError(
                    f"Неполный состав противника в войне {war.war_uid}: "
                    f"ожидалось {war.team_size}, получено {len(set(defender_positions))}"
                )
            result = await self.reconcile_war(
                war, list(war.attacks), defender_positions=defender_positions
            )
            attacks_checked += result.attacks_checked
            created += result.created
            updated += result.updated
            deleted += result.deleted
            unchanged += result.unchanged
            pending += result.pending
            created_attack_ids.extend(result.created_attack_ids)

        await self.session.flush()
        return ViolationRecalculationResult(
            wars_processed=len(wars), attacks_checked=attacks_checked,
            created=created, updated=updated, deleted=deleted, unchanged=unchanged,
            created_attack_ids=tuple(created_attack_ids),
            pending=pending,
        )

    async def reconcile_war(
        self,
        war,
        attacks: list,
        *,
        defender_positions: list[int],
    ) -> ViolationRecalculationResult:
        """Apply the shared domain decisions to automatic positional rows only."""
        decisions = evaluate_war_attack_violations(
            war.start_time, defender_positions, attacks,
            is_cwl=war.war_type == WarType.CWL,
            attacks_per_member=_attacks_per_member(war.source_payload),
            war_ended=war.state == WarState.WAR_ENDED,
            evaluated_at=utcnow(),
        )
        attack_ids = [attack.id for attack in attacks]
        violations_by_attack_id = {
            violation.attack_id: violation
            for violation in (
                await self.session.scalars(
                    select(Violation).where(Violation.attack_id.in_(attack_ids))
                )
            ).all()
        } if attack_ids else {}
        created = updated = deleted = unchanged = attacks_checked = pending = 0
        created_attack_ids: list[int] = []
        for attack in sorted(attacks, key=attack_order_key):
            attacks_checked += 1
            violation = violations_by_attack_id.get(attack.id)
            protected = violation is not None and (
                violation.is_manual or violation.code not in POSITIONAL_CODES
            )
            decision = decisions[attack.id]

            if protected:
                unchanged += 1
            elif (not decision.violated or not decision.is_final
                  or decision.code is None or decision.reason_text is None):
                if decision.violated and not decision.is_final:
                    pending += 1
                if violation is None:
                    unchanged += 1
                else:
                    await self.session.delete(violation)
                    violations_by_attack_id.pop(attack.id, None)
                    deleted += 1
            elif violation is None:
                violation = Violation(
                    attack_id=attack.id,
                    war_id=war.id,
                    player_tag=attack.attacker_tag,
                    code=decision.code,
                    reason_text=decision.reason_text,
                    player_position=attack.attacker_position,
                    target_position=attack.defender_position,
                    detected_at=attack.observed_at,
                    is_manual=False,
                )
                self.session.add(violation)
                violations_by_attack_id[attack.id] = violation
                created += 1
                created_attack_ids.append(attack.id)
            elif (
                violation.code != decision.code
                or violation.reason_text != decision.reason_text
                or violation.player_position != attack.attacker_position
                or violation.target_position != attack.defender_position
                or normalize_utc(violation.detected_at) != normalize_utc(attack.observed_at)
            ):
                violation.code = decision.code
                violation.reason_text = decision.reason_text
                violation.player_position = attack.attacker_position
                violation.target_position = attack.defender_position
                violation.detected_at = attack.observed_at
                updated += 1
            else:
                unchanged += 1
        await self.session.flush()
        return ViolationRecalculationResult(
            wars_processed=1,
            attacks_checked=attacks_checked,
            created=created,
            updated=updated,
            deleted=deleted,
            unchanged=unchanged,
            created_attack_ids=tuple(created_attack_ids),
            pending=pending,
        )


def _attacks_per_member(source_payload: dict | None) -> int | None:
    value = (source_payload or {}).get("attacksPerMember")
    return value if isinstance(value, int) and value > 0 else None

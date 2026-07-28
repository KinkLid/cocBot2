from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.violation_rules import evaluate_attack_violation
from app.models import Violation
from app.models.enums import ViolationCode
from app.repositories.war import WarRepository
from app.services.period import PeriodService


POSITIONAL_CODES = {ViolationCode.ABOVE_SELF, ViolationCode.TOO_LOW}


@dataclass(frozen=True, slots=True)
class ViolationRecalculationResult:
    wars_processed: int = 0
    attacks_checked: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0


class ViolationRecalculationService:
    """Reconcile saved automatic positional violations without API calls or notices."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.wars = WarRepository(session)
        self.periods = PeriodService(session)

    async def recalculate_current_cycle(self) -> ViolationRecalculationResult:
        period = await self.periods.current_cycle()
        wars = await self.wars.list_regular_wars_in_period(period.start, period.end)
        created = updated = deleted = unchanged = attacks_checked = 0

        for war in wars:
            defender_positions = sorted(
                participant.map_position
                for participant in war.participants
                if not participant.is_own_clan
            )
            attacks = sorted(war.attacks, key=lambda attack: (attack.observed_at, attack.id))
            previous_attacks = []
            for attack in attacks:
                attacks_checked += 1
                violation = attack.violation
                protected = violation is not None and (
                    violation.is_manual or violation.code not in POSITIONAL_CODES
                )
                decision = evaluate_attack_violation(
                    war_start_time=war.start_time,
                    attack_seen_at=attack.observed_at,
                    attacker_position=attack.attacker_position,
                    defender_position=attack.defender_position,
                    defender_positions=defender_positions,
                    allied_attacks=previous_attacks,
                )

                if protected:
                    unchanged += 1
                elif not decision.violated or decision.code is None or decision.reason_text is None:
                    if violation is None:
                        unchanged += 1
                    else:
                        await self.session.delete(violation)
                        deleted += 1
                elif violation is None:
                    self.session.add(
                        Violation(
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
                    )
                    created += 1
                elif (
                    violation.code != decision.code
                    or violation.reason_text != decision.reason_text
                    or violation.player_position != attack.attacker_position
                    or violation.target_position != attack.defender_position
                    or violation.detected_at != attack.observed_at
                ):
                    violation.code = decision.code
                    violation.reason_text = decision.reason_text
                    violation.player_position = attack.attacker_position
                    violation.target_position = attack.defender_position
                    violation.detected_at = attack.observed_at
                    updated += 1
                else:
                    unchanged += 1
                previous_attacks.append(attack)

        await self.session.flush()
        return ViolationRecalculationResult(
            wars_processed=len(wars),
            attacks_checked=attacks_checked,
            created=created,
            updated=updated,
            deleted=deleted,
            unchanged=unchanged,
        )

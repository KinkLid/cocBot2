from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Attack, CycleBoundary, Violation, War, WarParticipant


class WarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_war_by_uid(self, war_uid: str) -> War | None:
        result = await self.session.execute(
            select(War)
            .options(selectinload(War.participants), selectinload(War.attacks).selectinload(Attack.violation))
            .where(War.war_uid == war_uid)
        )
        return result.scalar_one_or_none()

    async def upsert_war(self, war: War) -> War:
        existing = await self.get_war_by_uid(war.war_uid)
        if existing is None:
            self.session.add(war)
            await self.session.flush()
            return war

        existing.state = war.state
        existing.opponent_tag = war.opponent_tag
        existing.opponent_name = war.opponent_name
        existing.team_size = war.team_size
        existing.is_friendly = war.is_friendly
        existing.start_time = war.start_time
        existing.end_time = war.end_time
        existing.preparation_start_time = war.preparation_start_time
        existing.source_payload = war.source_payload
        existing.league_group_id = war.league_group_id
        existing.cwl_season = war.cwl_season
        existing.round_index = war.round_index
        await self.session.flush()
        return existing

    async def replace_participants(self, war_id: int, participants: list[WarParticipant]) -> None:
        await self.session.execute(delete(WarParticipant).where(WarParticipant.war_id == war_id))
        for participant in participants:
            self.session.add(participant)
        await self.session.flush()

    async def get_attack(self, war_id: int, attacker_tag: str, defender_tag: str, attack_order: int) -> Attack | None:
        result = await self.session.execute(
            select(Attack).where(
                Attack.war_id == war_id,
                Attack.attacker_tag == attacker_tag,
                Attack.defender_tag == defender_tag,
                Attack.attack_order == attack_order,
            )
        )
        return result.scalar_one_or_none()

    async def add_attack(self, attack: Attack) -> Attack:
        self.session.add(attack)
        await self.session.flush()
        return attack

    async def get_violation_by_attack_id(self, attack_id: int) -> Violation | None:
        result = await self.session.execute(select(Violation).where(Violation.attack_id == attack_id))
        return result.scalar_one_or_none()

    async def add_violation(self, violation: Violation) -> Violation:
        self.session.add(violation)
        await self.session.flush()
        return violation

    async def delete_violation(self, violation: Violation) -> None:
        await self.session.delete(violation)
        await self.session.flush()

    async def upsert_cycle_boundary(self, source_key: str, boundary_at, description: str) -> CycleBoundary:
        result = await self.session.execute(select(CycleBoundary).where(CycleBoundary.source_key == source_key))
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = CycleBoundary(source_key=source_key, boundary_at=boundary_at, description=description)
            self.session.add(existing)
        else:
            existing.boundary_at = boundary_at
            existing.description = description
        await self.session.flush()
        return existing

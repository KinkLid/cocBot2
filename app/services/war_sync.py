from __future__ import annotations

import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.clash import ClashApiClient
from app.config.settings import AppYamlConfig
from app.domain.violation_rules import evaluate_attack_violation
from app.models import Attack, Violation, War, WarParticipant
from app.models.enums import WarState, WarType
from app.repositories.player_account import PlayerAccountRepository
from app.repositories.stats import StatsRepository
from app.repositories.war import WarRepository
from app.schemas.dto import CWLGroupDTO, WarDTO
from app.services.notifications import AdminNotifier
from app.services.period import PeriodService
from app.utils.time import parse_coc_time, utcnow

logger = logging.getLogger(__name__)


class WarSyncService:
    def __init__(
        self,
        session: AsyncSession,
        clash_client: ClashApiClient,
        config: AppYamlConfig,
        notifier: AdminNotifier,
    ) -> None:
        self.session = session
        self.clash_client = clash_client
        self.config = config
        self.notifier = notifier
        self.wars = WarRepository(session)
        self.players = PlayerAccountRepository(session)
        self.stats_repo = StatsRepository(session)
        self.period_service = PeriodService(session)

    async def sync_all(self) -> None:
        regular = await self.clash_client.get_current_war(self.config.main_clan_tag)
        if regular and not regular.is_friendly:
            await self._persist_war(regular)

        cwl_group = await self.clash_client.get_cwl_group(self.config.main_clan_tag)
        if cwl_group is not None:
            await self._sync_cwl_group(cwl_group)

        await self.session.commit()

    async def _sync_cwl_group(self, group: CWLGroupDTO) -> None:
        all_end_times = []
        for round_index, round_data in enumerate(group.rounds):
            for war_tag in round_data.get("warTags", []):
                if war_tag == "#0":
                    continue
                war = await self.clash_client.get_cwl_war(
                    war_tag,
                    clan_tag=self.config.main_clan_tag,
                    league_group_id=group.league_group_id,
                    season=group.season,
                    round_index=round_index,
                )
                if war.clan.tag != self.config.main_clan_tag and war.opponent.tag != self.config.main_clan_tag:
                    continue
                await self._persist_war(war)
                if war.end_time:
                    all_end_times.append(parse_coc_time(war.end_time))

        valid_end_times = [item for item in all_end_times if item is not None]
        if valid_end_times and max(valid_end_times) <= utcnow():
            await self.wars.upsert_cycle_boundary(
                source_key=f"cwl:{group.season}",
                boundary_at=max(valid_end_times),
                description=f"Окончание ЛВК {group.season}",
            )

    async def _persist_war(self, dto: WarDTO) -> War:
        own_side = dto.clan if dto.clan.tag == self.config.main_clan_tag else dto.opponent
        enemy_side = dto.opponent if own_side.tag == dto.clan.tag else dto.clan

        war_uid = self._war_uid(dto, own_side.tag, enemy_side.tag)
        war = await self.wars.upsert_war(
            War(
                war_uid=war_uid,
                clan_tag=own_side.tag,
                clan_name=own_side.name,
                opponent_tag=enemy_side.tag,
                opponent_name=enemy_side.name,
                war_type=dto.war_type,
                state=self._map_state(dto.state),
                league_group_id=dto.league_group_id,
                cwl_season=dto.cwl_season,
                round_index=dto.round_index,
                team_size=dto.team_size,
                is_friendly=dto.is_friendly,
                start_time=parse_coc_time(dto.start_time),
                end_time=parse_coc_time(dto.end_time),
                preparation_start_time=parse_coc_time(dto.preparation_start_time),
                source_payload=dto.raw_payload or {},
            )
        )

        own_members_by_tag = {member.tag: member for member in own_side.members}
        enemy_members_by_tag = {member.tag: member for member in enemy_side.members}

        own_participants_by_tag: dict[str, WarParticipant] = {}
        enemy_participants_by_tag: dict[str, WarParticipant] = {}
        participants: list[WarParticipant] = []
        for is_own, side, participant_map in (
            (True, own_side, own_participants_by_tag),
            (False, enemy_side, enemy_participants_by_tag),
        ):
            for member in side.members:
                player = await self.players.get_by_tag(member.tag) if is_own else None
                participant = WarParticipant(
                    war_id=war.id,
                    player_id=player.id if player else None,
                    player_tag=member.tag,
                    name=member.name,
                    map_position=member.map_position,
                    town_hall=member.town_hall_level,
                    is_own_clan=is_own,
                )
                participant_map[member.tag] = participant
                participants.append(participant)
        await self.wars.replace_participants(war.id, participants)

        for member in own_side.members:
            attacker_member = own_members_by_tag[member.tag]
            attacker_player = await self.players.get_by_tag(member.tag)
            attacker_player_id = attacker_player.id if attacker_player else None
            for attack_dto in member.attacks:
                defender_member = enemy_members_by_tag.get(attack_dto.defender_tag)
                if defender_member is None:
                    logger.warning(
                        "Cannot build attack snapshot from war roster: war_uid=%s attacker_tag=%s defender_tag=%s",
                        war.war_uid,
                        member.tag,
                        attack_dto.defender_tag,
                    )
                    continue

                attacker_position = attacker_member.map_position
                attacker_th = attacker_member.town_hall_level
                attacker_name = attacker_member.name
                defender_position = defender_member.map_position
                defender_th = defender_member.town_hall_level
                defender_name = defender_member.name

                existing_attack = await self.wars.get_attack(war.id, member.tag, attack_dto.defender_tag, attack_dto.order)
                if existing_attack is not None:
                    existing_attack.attacker_name = attacker_name
                    existing_attack.attacker_position = attacker_position
                    existing_attack.attacker_town_hall = attacker_th
                    existing_attack.defender_name = defender_name
                    existing_attack.defender_position = defender_position
                    existing_attack.defender_town_hall = defender_th
                    existing_attack.stars = attack_dto.stars
                    existing_attack.destruction = attack_dto.destruction_percentage
                    await self._reconcile_violation(war, existing_attack)
                    continue
                observed_at = utcnow()
                attack = await self.wars.add_attack(
                    Attack(
                        war_id=war.id,
                        attacker_player_id=attacker_player_id,
                        attacker_tag=member.tag,
                        attacker_name=attacker_name,
                        attacker_position=attacker_position,
                        attacker_town_hall=attacker_th,
                        defender_tag=attack_dto.defender_tag,
                        defender_name=defender_name,
                        defender_position=defender_position,
                        defender_town_hall=defender_th,
                        stars=attack_dto.stars,
                        destruction=attack_dto.destruction_percentage,
                        attack_order=attack_dto.order,
                        observed_at=observed_at,
                    )
                )
                await self._reconcile_violation(war, attack)
        return war

    async def _reconcile_violation(self, war: War, attack: Attack) -> None:
        if war.is_friendly:
            return

        decision = evaluate_attack_violation(
            war_start_time=war.start_time,
            attack_seen_at=attack.observed_at,
            attacker_position=attack.attacker_position,
            defender_position=attack.defender_position,
        )
        violation = await self.wars.get_violation_by_attack_id(attack.id)

        if not decision.violated or decision.code is None or decision.reason_text is None:
            if violation is not None:
                await self.wars.delete_violation(violation)
            return

        if violation is None:
            violation = await self.wars.add_violation(
                Violation(
                    attack_id=attack.id,
                    war_id=war.id,
                    player_tag=attack.attacker_tag,
                    code=decision.code,
                    reason_text=decision.reason_text,
                    player_position=attack.attacker_position,
                    target_position=attack.defender_position,
                    detected_at=attack.observed_at,
                )
            )
            current_cycle = await self.period_service.current_cycle(attack.observed_at)
            violation_number = await self.stats_repo.violation_count_for_player(attack.attacker_tag, current_cycle.start, current_cycle.end)
            war_label = "ЛВК" if war.war_type == WarType.CWL else "КВ"
            text = (
                f"🚨 Нарушение атаки\n"
                f"Игрок: {attack.attacker_name} {attack.attacker_tag}\n"
                f"Война: {war_label}\n"
                f"Время фиксации: {attack.observed_at:%Y-%m-%d %H:%M:%S UTC}\n"
                f"Нарушение №{violation_number}\n"
                f"Цель: {attack.defender_name} {attack.defender_tag}\n"
                f"Позиция игрока: {attack.attacker_position}\n"
                f"Позиция цели: {attack.defender_position}\n"
                f"Причина: {violation.reason_text}"
            )
            await self.notifier.notify_once(
                event_key=f"violation:{attack.id}",
                event_type="violation",
                text=text,
                now=attack.observed_at,
            )
            logger.info("Violation recorded for attack %s", attack.id)
            return

        violation.code = decision.code
        violation.reason_text = decision.reason_text
        violation.player_position = attack.attacker_position
        violation.target_position = attack.defender_position
        violation.detected_at = attack.observed_at
        await self.session.flush()

    def _war_uid(self, dto: WarDTO, own_tag: str, enemy_tag: str) -> str:
        base_time = dto.preparation_start_time or dto.start_time or dto.end_time or "unknown"
        return f"{dto.war_type}:{own_tag}:{enemy_tag}:{base_time}:{dto.round_index or 0}"

    def _map_state(self, state: str) -> WarState:
        mapping = {
            "preparation": WarState.PREPARATION,
            "inWar": WarState.IN_WAR,
            "warEnded": WarState.WAR_ENDED,
            "notInWar": WarState.NOT_IN_WAR,
        }
        return mapping.get(state, WarState.NOT_IN_WAR)

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attack, PlayerAccount, TelegramPlayerLink, TelegramUser, Violation, War, WarParticipant
from app.models.enums import WarType


@dataclass(slots=True)
class AggregatedStatsRow:
    player_tag: str
    player_name: str
    town_hall: int
    telegram_id: int | None
    telegram_username: str | None
    registered_at: datetime | None
    clan_rank: int | None
    wars: int
    attacks: int
    stars: int
    violations: int


class StatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def aggregated_player_stats(
        self,
        *,
        clan_tag: str,
        period_start: datetime,
        period_end: datetime,
        player_tags: list[str] | None = None,
    ) -> list[AggregatedStatsRow]:
        attacks_subq = (
            select(
                Attack.attacker_tag.label("player_tag"),
                func.count(Attack.id).label("attacks"),
                func.coalesce(func.sum(Attack.stars), 0).label("stars"),
            )
            .join(War, War.id == Attack.war_id)
            .where(
                War.clan_tag == clan_tag,
                Attack.observed_at >= period_start,
                Attack.observed_at <= period_end,
            )
            .group_by(Attack.attacker_tag)
            .subquery()
        )

        wars_subq = (
            select(
                WarParticipant.player_tag.label("player_tag"),
                func.count(WarParticipant.id).label("wars"),
            )
            .join(War, War.id == WarParticipant.war_id)
            .where(
                War.clan_tag == clan_tag,
                WarParticipant.is_own_clan.is_(True),
                War.start_time >= period_start,
                War.start_time <= period_end,
            )
            .group_by(WarParticipant.player_tag)
            .subquery()
        )

        violations_subq = (
            select(
                Violation.player_tag.label("player_tag"),
                func.count(Violation.id).label("violations"),
            )
            .where(Violation.detected_at >= period_start, Violation.detected_at <= period_end)
            .group_by(Violation.player_tag)
            .subquery()
        )

        stmt = (
            select(
                PlayerAccount.player_tag,
                PlayerAccount.name,
                PlayerAccount.town_hall,
                TelegramUser.telegram_id,
                TelegramUser.username,
                TelegramUser.registered_at,
                PlayerAccount.current_clan_rank,
                func.coalesce(wars_subq.c.wars, 0),
                func.coalesce(attacks_subq.c.attacks, 0),
                func.coalesce(attacks_subq.c.stars, 0),
                func.coalesce(violations_subq.c.violations, 0),
            )
            .outerjoin(attacks_subq, attacks_subq.c.player_tag == PlayerAccount.player_tag)
            .outerjoin(wars_subq, wars_subq.c.player_tag == PlayerAccount.player_tag)
            .outerjoin(violations_subq, violations_subq.c.player_tag == PlayerAccount.player_tag)
            .outerjoin(TelegramPlayerLink, TelegramPlayerLink.player_tag == PlayerAccount.player_tag)
            .outerjoin(TelegramUser, TelegramUser.id == TelegramPlayerLink.telegram_user_id)
            .where(PlayerAccount.current_in_clan.is_(True), PlayerAccount.current_clan_tag == clan_tag)
            .order_by(PlayerAccount.current_clan_rank.asc().nulls_last(), PlayerAccount.name.asc())
        )
        if player_tags:
            stmt = stmt.where(PlayerAccount.player_tag.in_(player_tags))

        rows = (await self.session.execute(stmt)).all()
        dedup: dict[str, AggregatedStatsRow] = {}
        for row in rows:
            if row[0] in dedup:
                continue
            dedup[row[0]] = AggregatedStatsRow(
                player_tag=row[0],
                player_name=row[1],
                town_hall=row[2],
                telegram_id=row[3],
                telegram_username=row[4],
                registered_at=row[5],
                clan_rank=row[6],
                wars=row[7],
                attacks=row[8],
                stars=row[9],
                violations=row[10],
            )
        return list(dedup.values())

    async def attack_rows_for_players(self, clan_tag: str, period_start: datetime, period_end: datetime, player_tags: list[str]) -> list:
        stmt = (
            select(Attack, War, Violation)
            .join(War, War.id == Attack.war_id)
            .outerjoin(Violation, Violation.attack_id == Attack.id)
            .where(
                War.clan_tag == clan_tag,
                Attack.attacker_tag.in_(player_tags),
                Attack.observed_at >= period_start,
                Attack.observed_at <= period_end,
            )
            .order_by(Attack.observed_at.asc())
        )
        return list((await self.session.execute(stmt)).all())

    async def participation_rows_for_players(self, clan_tag: str, period_start: datetime, period_end: datetime, player_tags: list[str]) -> list:
        stmt = (
            select(WarParticipant, War)
            .join(War, War.id == WarParticipant.war_id)
            .where(
                War.clan_tag == clan_tag,
                WarParticipant.player_tag.in_(player_tags),
                WarParticipant.is_own_clan.is_(True),
                War.start_time >= period_start,
                War.start_time <= period_end,
            )
            .order_by(War.start_time.asc())
        )
        return list((await self.session.execute(stmt)).all())

    async def violation_count_for_player(self, player_tag: str, period_start: datetime, period_end: datetime) -> int:
        stmt = select(func.count(Violation.id)).where(
            Violation.player_tag == player_tag,
            Violation.detected_at >= period_start,
            Violation.detected_at <= period_end,
        )
        return int((await self.session.execute(stmt)).scalar_one())

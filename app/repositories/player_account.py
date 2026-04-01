from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClanMembershipHistory, PlayerAccount


class PlayerAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_tag(self, player_tag: str) -> PlayerAccount | None:
        result = await self.session.execute(select(PlayerAccount).where(PlayerAccount.player_tag == player_tag))
        return result.scalar_one_or_none()

    async def upsert_player(
        self,
        *,
        player_tag: str,
        name: str,
        town_hall: int,
        now: datetime,
        clan_tag: str | None,
        clan_name: str | None,
        clan_rank: int | None,
        in_clan: bool,
    ) -> PlayerAccount:
        player = await self.get_by_tag(player_tag)
        if player is None:
            player = PlayerAccount(
                player_tag=player_tag,
                name=name,
                town_hall=town_hall,
                current_clan_tag=clan_tag,
                current_clan_name=clan_name,
                current_clan_rank=clan_rank,
                current_in_clan=in_clan,
                last_seen_in_clan_at=now if in_clan else None,
                first_absent_at=None if in_clan else now,
                created_at=now,
                updated_at=now,
            )
            self.session.add(player)
            await self.session.flush()
            return player

        player.name = name
        player.town_hall = town_hall
        player.current_clan_tag = clan_tag
        player.current_clan_name = clan_name
        player.current_clan_rank = clan_rank
        player.current_in_clan = in_clan
        if in_clan:
            player.last_seen_in_clan_at = now
            player.first_absent_at = None
        else:
            player.first_absent_at = player.first_absent_at or now
        player.updated_at = now
        await self.session.flush()
        return player

    async def mark_absent(self, player: PlayerAccount, now: datetime) -> None:
        player.current_in_clan = False
        player.current_clan_tag = None
        player.current_clan_name = None
        player.current_clan_rank = None
        player.first_absent_at = player.first_absent_at or now
        player.updated_at = now

    async def active_clan_members(self, clan_tag: str) -> list[PlayerAccount]:
        result = await self.session.execute(
            select(PlayerAccount)
            .where(PlayerAccount.current_in_clan.is_(True), PlayerAccount.current_clan_tag == clan_tag)
            .order_by(PlayerAccount.current_clan_rank.asc().nulls_last(), PlayerAccount.name.asc())
        )
        return list(result.scalars().all())

    async def absent_players(self) -> list[PlayerAccount]:
        result = await self.session.execute(select(PlayerAccount).where(PlayerAccount.current_in_clan.is_(False)))
        return list(result.scalars().all())

    async def open_membership(self, player_id: int, clan_tag: str) -> ClanMembershipHistory | None:
        result = await self.session.execute(
            select(ClanMembershipHistory).where(
                ClanMembershipHistory.player_id == player_id,
                ClanMembershipHistory.clan_tag == clan_tag,
                ClanMembershipHistory.left_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def open_or_create_membership(self, player_id: int, clan_tag: str, now: datetime) -> ClanMembershipHistory:
        membership = await self.open_membership(player_id, clan_tag)
        if membership is None:
            membership = ClanMembershipHistory(player_id=player_id, clan_tag=clan_tag, joined_at=now, left_at=None)
            self.session.add(membership)
            await self.session.flush()
        return membership

    async def close_membership(self, player_id: int, clan_tag: str, now: datetime) -> None:
        membership = await self.open_membership(player_id, clan_tag)
        if membership is not None:
            membership.left_at = now

    async def delete_player_fully(self, player_id: int) -> None:
        await self.session.execute(delete(PlayerAccount).where(PlayerAccount.id == player_id))

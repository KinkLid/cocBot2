from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.session import create_engine_and_sessionmaker
from app.models import PlayerAccount, TelegramPlayerLink, TelegramUser

logger = logging.getLogger("recover_links")


@dataclass
class RecoveryStats:
    created_telegram_users: int = 0
    updated_telegram_users: int = 0
    created_player_accounts: int = 0
    updated_player_accounts: int = 0
    created_links: int = 0
    skipped_without_telegram_id: int = 0
    skipped_conflicts: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover Telegram links from exported JSON")
    parser.add_argument("json_path", type=Path, help="Path to JSON export file")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB, only print summary")
    return parser.parse_args()


def parse_registered_at(value: str | None, player_tag: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        logger.warning("Invalid registered_at for %s: %r", player_tag, value)
        return None


def load_players(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        logger.error("JSON file not found: %s", path)
        raise SystemExit(1) from exc
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON file: %s", exc)
        raise SystemExit(1) from exc

    players = payload.get("players")
    if not isinstance(players, list):
        logger.error("JSON must contain list field 'players'")
        raise SystemExit(1)
    return [item for item in players if isinstance(item, dict)]


async def recover_links(session: AsyncSession, players: list[dict[str, Any]]) -> RecoveryStats:
    stats = RecoveryStats()

    for item in players:
        telegram_id = item.get("telegram_id")
        player_tag = item.get("player_tag")
        if not telegram_id:
            stats.skipped_without_telegram_id += 1
            logger.info("Skip player without telegram_id: %s", player_tag)
            continue
        if not player_tag:
            logger.warning("Skip row with telegram_id=%s due to missing player_tag", telegram_id)
            continue

        tg_user = await session.scalar(select(TelegramUser).where(TelegramUser.telegram_id == int(telegram_id)))
        if tg_user is None:
            tg_user = TelegramUser(telegram_id=int(telegram_id), username=item.get("telegram_username"))
            parsed_registered_at = parse_registered_at(item.get("registered_at"), player_tag)
            if parsed_registered_at is not None:
                tg_user.registered_at = parsed_registered_at
            session.add(tg_user)
            await session.flush()
            stats.created_telegram_users += 1
            logger.info("Created telegram user %s", telegram_id)
        else:
            updated = False
            username = item.get("telegram_username")
            if username and tg_user.username != username:
                tg_user.username = username
                updated = True
            if tg_user.registered_at is None:
                parsed_registered_at = parse_registered_at(item.get("registered_at"), player_tag)
                if parsed_registered_at is not None:
                    tg_user.registered_at = parsed_registered_at
                    updated = True
            if updated:
                stats.updated_telegram_users += 1
                logger.info("Updated telegram user %s", telegram_id)

        player = await session.scalar(select(PlayerAccount).where(PlayerAccount.player_tag == str(player_tag)))
        if player is None:
            now = datetime.now(UTC)
            player = PlayerAccount(
                player_tag=str(player_tag),
                name=item.get("player_name") or str(player_tag),
                town_hall=int(item.get("town_hall") or 1),
                current_in_clan=False,
                created_at=now,
                updated_at=now,
            )
            session.add(player)
            stats.created_player_accounts += 1
            logger.info("Created player account %s", player_tag)
        else:
            updated = False
            new_name = item.get("player_name")
            if new_name and player.name != new_name:
                player.name = new_name
                updated = True
            new_town_hall = item.get("town_hall")
            if new_town_hall is not None:
                th = int(new_town_hall)
                if player.town_hall != th:
                    player.town_hall = th
                    updated = True
            if updated:
                player.updated_at = datetime.now(UTC)
                stats.updated_player_accounts += 1
                logger.info("Updated player account %s", player_tag)

        conflict = await session.scalar(
            select(TelegramPlayerLink)
            .where(TelegramPlayerLink.player_tag == str(player_tag))
            .where(TelegramPlayerLink.telegram_user_id != tg_user.id)
        )
        if conflict:
            stats.skipped_conflicts += 1
            logger.warning(
                "Conflict for %s: already linked to telegram_user_id=%s, skip link to telegram_id=%s",
                player_tag,
                conflict.telegram_user_id,
                telegram_id,
            )
            continue

        existing_link = await session.scalar(
            select(TelegramPlayerLink)
            .where(TelegramPlayerLink.telegram_user_id == tg_user.id)
            .where(TelegramPlayerLink.player_tag == str(player_tag))
        )
        if existing_link is None:
            session.add(
                TelegramPlayerLink(
                    telegram_user_id=tg_user.id,
                    player_tag=str(player_tag),
                    linked_at=datetime.now(UTC),
                )
            )
            stats.created_links += 1
            logger.info("Created link telegram_id=%s -> %s", telegram_id, player_tag)

    return stats


async def run_recovery(json_path: Path, dry_run: bool) -> RecoveryStats:
    settings = Settings()
    engine, session_maker = create_engine_and_sessionmaker(settings)
    players = load_players(json_path)

    try:
        async with session_maker() as session:
            stats = await recover_links(session, players)
            if dry_run:
                await session.rollback()
                logger.info("Dry-run finished, transaction rolled back")
            else:
                await session.commit()
                logger.info("Recovery committed")
            return stats
    finally:
        await engine.dispose()


def print_summary(stats: RecoveryStats) -> None:
    print("Recovery summary:")
    print(f"  created telegram users: {stats.created_telegram_users}")
    print(f"  updated telegram users: {stats.updated_telegram_users}")
    print(f"  created player accounts: {stats.created_player_accounts}")
    print(f"  updated player accounts: {stats.updated_player_accounts}")
    print(f"  created links: {stats.created_links}")
    print(f"  skipped players without telegram_id: {stats.skipped_without_telegram_id}")
    print(f"  skipped conflicts: {stats.skipped_conflicts}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    stats = asyncio.run(run_recovery(args.json_path, dry_run=args.dry_run))
    print_summary(stats)


if __name__ == "__main__":
    main()

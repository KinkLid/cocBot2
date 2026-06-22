#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path
from sqlalchemy.engine import make_url
from alembic.config import Config
from alembic.script import ScriptDirectory


def load_settings(project_dir: Path):
    sys.path.insert(0, str(project_dir))
    os.chdir(project_dir)
    from app.config.settings import Settings  # noqa: PLC0415

    settings = Settings()
    config = settings.load_yaml_config()
    return settings, config


def sqlite_path(project_dir: Path, settings) -> Path:
    url = make_url(settings.migration_database_url)
    if url.get_backend_name() != "sqlite":
        raise RuntimeError("Автоматический перенос сейчас поддерживает только SQLite.")
    db = url.database
    if not db or db == ":memory:":
        raise RuntimeError("SQLite database file is not configured")
    path = Path(db).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve()


async def online(project_dir: Path) -> dict[str, object]:
    settings, config = load_settings(project_dir)
    token = settings.bot_token
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getMe")
    with urllib.request.urlopen(req, timeout=settings.telegram_request_timeout_seconds) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError("Telegram getMe failed")
    from app.clients.clash import HttpClashApiClient  # noqa: PLC0415

    async with HttpClashApiClient(settings.clash_api_token, timeout_seconds=settings.clash_request_timeout_seconds) as client:
        clan = await client.get_clan(config.main_clan_tag)
        members = await client.get_clan_members(config.main_clan_tag)
    tags = {m.tag for m in members}
    reported = int(clan.get("members", -1))
    received = len(tags)
    if received <= 0:
        raise RuntimeError("Clash clan members list is empty")
    if reported != received:
        raise RuntimeError(f"Clash roster mismatch: reported={reported} received={received}")
    return {"telegram_ok": True, "clash_ok": True, "clan_tag": config.main_clan_tag, "clan_reported_members": reported, "clan_received_members": received}


def offline(project_dir: Path, expected_active_players: int) -> dict[str, object]:
    settings, _config = load_settings(project_dir)
    db = sqlite_path(project_dir, settings)
    alembic_cfg = Config(str(project_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(alembic_cfg)
    head = script.get_current_head()
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("alembic_version", "player_accounts", "manual_contribution_adjustments"):
            if table not in tables:
                raise RuntimeError(f"Required table is missing: {table}")
        current = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        if current != head:
            raise RuntimeError(f"Alembic revision mismatch: current={current} head={head}")
        active = conn.execute("SELECT COUNT(*) FROM player_accounts WHERE current_in_clan = 1").fetchone()[0]
        if int(active) != int(expected_active_players):
            raise RuntimeError(f"Active players mismatch: expected={expected_active_players} actual={active}")
        columns = {r[1] for r in conn.execute("PRAGMA table_info(manual_contribution_adjustments)")}
        if "operation_token" not in columns:
            raise RuntimeError("operation_token column is missing")
    return {"offline_ok": True, "integrity": integrity, "alembic_revision": current, "alembic_head": head, "active_players": int(active)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--online-only", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--expected-active-players", type=int)
    args = parser.parse_args()
    try:
        project_dir = Path(args.project_dir).resolve()
        if args.online_only:
            result = asyncio.run(online(project_dir))
        elif args.offline:
            if args.expected_active_players is None:
                raise RuntimeError("--expected-active-players is required with --offline")
            result = offline(project_dir, args.expected_active_players)
        else:
            raise RuntimeError("Specify --online-only or --offline")
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"check_server_health.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

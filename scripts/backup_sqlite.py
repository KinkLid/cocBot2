#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from sqlalchemy.engine import make_url


def _load_settings(project_dir: Path):
    sys.path.insert(0, str(project_dir))
    os.chdir(project_dir)
    from app.config.settings import Settings  # noqa: PLC0415

    return Settings()


def sqlite_path(project_dir: Path) -> Path:
    settings = _load_settings(project_dir)
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    project_dir = Path(args.project_dir).resolve()
    output = Path(args.output).expanduser().resolve()
    try:
        source_path = sqlite_path(project_dir)
        if not source_path.is_file():
            raise RuntimeError(f"SQLite database file does not exist: {source_path}")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as source, sqlite3.connect(output) as destination:
            source.backup(destination)
        with sqlite3.connect(output) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {integrity}")
            active_players = conn.execute("SELECT COUNT(*) FROM player_accounts WHERE current_in_clan = 1").fetchone()[0]
        result = {
            "path": str(output),
            "sha256": sha256_file(output),
            "size_bytes": output.stat().st_size,
            "integrity": integrity,
            "active_players": int(active_players),
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:
        try:
            if output.exists():
                output.unlink()
        finally:
            print(f"backup_sqlite.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

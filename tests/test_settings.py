from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings, ensure_sqlite_database_parent_dir, make_sync_sqlalchemy_url


def test_make_sync_sqlalchemy_url_converts_async_sqlite_url() -> None:
    assert make_sync_sqlalchemy_url("sqlite+aiosqlite:///./data/clanbot.sqlite3") == "sqlite:///./data/clanbot.sqlite3"


def test_migration_database_url_prefers_explicit_sync_url() -> None:
    settings = Settings(
        bot_token="123:TEST",
        clash_api_token="CLASH_TOKEN",
        database_url="sqlite+aiosqlite:///./data/runtime.sqlite3",
        database_url_sync="sqlite:///./data/migrations.sqlite3",
    )

    assert settings.migration_database_url == "sqlite:///./data/migrations.sqlite3"


def test_make_sync_sqlalchemy_url_preserves_absolute_sqlite_path() -> None:
    assert make_sync_sqlalchemy_url("sqlite+aiosqlite:////root/cocBot2/data/clanbot.db") == "sqlite:////root/cocBot2/data/clanbot.db"


def test_ensure_sqlite_database_parent_dir_creates_missing_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "db" / "clanbot.sqlite3"
    ensure_sqlite_database_parent_dir(f"sqlite:///{db_path}")

    assert db_path.parent.exists()

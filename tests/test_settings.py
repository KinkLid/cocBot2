from __future__ import annotations

from app.config.settings import Settings, make_sync_sqlalchemy_url


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

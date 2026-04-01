from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class PollingIntervals(BaseModel):
    active_war_seconds: int = 90
    clan_members_seconds: int = 900
    housekeeping_seconds: int = 3600


class AppYamlConfig(BaseModel):
    main_clan_tag: str
    admin_telegram_ids: list[int] = Field(default_factory=list)
    clan_chat_url: str | None = None
    polling: PollingIntervals = Field(default_factory=PollingIntervals)
    log_level: str = "INFO"

    @field_validator("main_clan_tag")
    @classmethod
    def normalize_clan_tag(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.startswith("#"):
            value = f"#{value}"
        return value


class Settings(BaseSettings):
    bot_token: str
    clash_api_token: str
    database_url: str = "sqlite+aiosqlite:///./data/clanbot.sqlite3"
    database_url_sync: str | None = None
    config_path: str = "./config.yaml"
    log_file: str = "./logs/clanbot.log"
    telegram_request_timeout_seconds: int = 20
    clash_request_timeout_seconds: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def migration_database_url(self) -> str:
        if self.database_url_sync:
            return self.database_url_sync
        return make_sync_sqlalchemy_url(self.database_url)

    def load_yaml_config(self) -> AppYamlConfig:
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"Файл конфигурации не найден: {path}")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return AppYamlConfig.model_validate(data)


def make_sync_sqlalchemy_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and "+" in url.drivername:
        return str(url.set(drivername="sqlite"))
    return database_url


def ensure_sqlite_database_parent_dir(database_url: str | URL) -> None:
    url = make_url(str(database_url))
    if url.get_backend_name() != "sqlite":
        return

    db_path = url.database
    if not db_path or db_path == ":memory:":
        return

    Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

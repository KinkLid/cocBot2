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


class BotCommandBaseline(BaseModel):
    command: str
    description: str


class TelegramSecurityConfig(BaseModel):
    expected_bot_id: int | None = None
    expected_username: str | None = None
    expected_display_name: str | None = None
    expected_description: str | None = None
    expected_short_description: str | None = None
    expected_commands: list[BotCommandBaseline] | None = None
    restore_profile: bool = False
    monitor_interval_seconds: int = Field(default=45, ge=30, le=300)


class AppYamlConfig(BaseModel):
    main_clan_tag: str
    admin_telegram_ids: list[int] = Field(default_factory=list)
    clan_chat_url: str | None = None
    polling: PollingIntervals = Field(default_factory=PollingIntervals)
    log_level: str = "INFO"
    telegram_security: TelegramSecurityConfig = Field(default_factory=TelegramSecurityConfig)

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
    security_audit_file: str = "./logs/security-audit.jsonl"
    security_state_file: str = "./data/security-state.json"
    update_audit_file: str = "./logs/update-audit.jsonl"
    sentinel_bot_token: str | None = None
    sentinel_admin_chat_ids: str = ""

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

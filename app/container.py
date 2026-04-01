from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.clash import ClashApiClient, HttpClashApiClient
from app.config.settings import AppYamlConfig, Settings
from app.services.auth import AuthService
from app.services.logs import LogService


@dataclass(slots=True)
class AppContext:
    settings: Settings
    config: AppYamlConfig
    session_maker: async_sessionmaker[AsyncSession]
    clash_client: ClashApiClient
    auth_service: AuthService
    log_service: LogService
    export_dir: Path = Path("./exports")


async def send_text_via_bot(bot: Bot, chat_id: int, text: str) -> None:
    await bot.send_message(chat_id=chat_id, text=text)


def build_context(settings: Settings, config: AppYamlConfig, session_maker: async_sessionmaker[AsyncSession]) -> AppContext:
    clash_client = HttpClashApiClient(settings.clash_api_token, timeout_seconds=settings.clash_request_timeout_seconds)
    return AppContext(
        settings=settings,
        config=config,
        session_maker=session_maker,
        clash_client=clash_client,
        auth_service=AuthService(config),
        log_service=LogService(settings.log_file),
    )

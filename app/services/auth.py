from __future__ import annotations

from app.config.settings import AppYamlConfig


class AuthService:
    def __init__(self, config: AppYamlConfig) -> None:
        self.config = config

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in set(self.config.admin_telegram_ids)

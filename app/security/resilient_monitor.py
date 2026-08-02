from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram.exceptions import TelegramNetworkError

from app.security.audit import utc_now
from app.security.monitor import SecurityViolation, TelegramSecurityMonitor, safe_error

logger = logging.getLogger("security")
_NETWORK_ALERT_THRESHOLD = 3


class ResilientTelegramSecurityMonitor(TelegramSecurityMonitor):
    """Security monitor that separates Telegram transport failures from incidents."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._consecutive_network_failures = 0
        self._network_failure_alert_delivered = False

    @staticmethod
    def _network_stage(exc: TelegramNetworkError) -> str:
        method = getattr(exc, "method", None)
        if method is None:
            return "unknown"
        return type(method).__name__

    async def _handle_network_failure(self, exc: TelegramNetworkError) -> None:
        self._consecutive_network_failures += 1
        failure_count = self._consecutive_network_failures
        stage = self._network_stage(exc)
        self._audit(
            "security_check_network_failed",
            severity="WARNING",
            result="transient_failure",
            bot_id=self.bot_id,
            check_stage=stage,
            consecutive_failures=failure_count,
            **safe_error(exc),
        )
        logger.warning(
            "Telegram security check network failure: stage=%s consecutive=%s",
            stage,
            failure_count,
        )
        if failure_count < _NETWORK_ALERT_THRESHOLD:
            return

        delivered = await self.alerts.send(
            "security_check_network_failed",
            (
                "⚠️ Telegram API временно недоступен для проверки безопасности. "
                f"Подряд ошибок: {failure_count}. Этап: {stage}. "
                "Бот продолжает работу; проверка будет повторена автоматически."
            ),
            bot_id=self.bot_id,
            severity="WARNING",
        )
        self._network_failure_alert_delivered = self._network_failure_alert_delivered or delivered

    async def _handle_successful_check(self) -> None:
        previous_failures = self._consecutive_network_failures
        alert_was_delivered = self._network_failure_alert_delivered
        self._consecutive_network_failures = 0
        self._network_failure_alert_delivered = False
        if previous_failures == 0:
            return

        self._audit(
            "security_check_network_recovered",
            severity="INFO",
            result="recovered",
            bot_id=self.bot_id,
            previous_consecutive_failures=previous_failures,
        )
        if alert_was_delivered:
            await self.alerts.send(
                "security_check_network_recovered",
                (
                    "✅ Соединение с Telegram API восстановлено. "
                    f"Проверка безопасности снова проходит успешно после {previous_failures} ошибок подряд."
                ),
                bot_id=self.bot_id,
                severity="INFO",
            )

    def _reset_network_failure_state(self) -> None:
        self._consecutive_network_failures = 0
        self._network_failure_alert_delivered = False

    async def run_forever(self) -> None:
        self._audit("security_monitor_started", bot_id=self.bot_id)
        while True:
            await asyncio.sleep(self.config.telegram_security.monitor_interval_seconds)
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except SecurityViolation:
                raise
            except TelegramNetworkError as exc:
                await self._handle_network_failure(exc)
            except Exception as exc:
                self._reset_network_failure_state()
                self._audit(
                    "security_check_failed",
                    severity="ERROR",
                    result="transient_failure",
                    bot_id=self.bot_id,
                    **safe_error(exc),
                )
                await self.alerts.send(
                    "security_check_failed",
                    f"ERROR security_check_failed UTC={utc_now()} bot={self.bot_id}/@{self.username}.",
                    bot_id=self.bot_id,
                    severity="ERROR",
                )
            else:
                await self._handle_successful_check()

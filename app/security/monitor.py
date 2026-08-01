from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.types import BotCommand

from app.config.settings import AppYamlConfig
from app.security.audit import JsonlAudit, SecurityState, git_revision, utc_now

logger = logging.getLogger("security")


class SecurityViolation(RuntimeError):
    pass


def safe_error(exc: BaseException) -> dict[str, str]:
    return {"error_class": type(exc).__name__}


def webhook_metadata(info: Any) -> dict[str, Any]:
    parsed = urlsplit(info.url)
    return {
        "webhook_scheme": parsed.scheme or None, "webhook_hostname": parsed.hostname,
        "webhook_port": parsed.port, "webhook_url_fingerprint": hashlib.sha256(info.url.encode()).hexdigest()[:12],
        "pending_update_count": info.pending_update_count, "last_error_date": str(info.last_error_date) if info.last_error_date else None,
        "last_error_message": info.last_error_message, "max_connections": info.max_connections,
        "allowed_updates": [str(x) for x in info.allowed_updates] if info.allowed_updates else None,
    }


class SecurityAlerts:
    def __init__(self, primary: Bot, audit: JsonlAudit, admin_ids: list[int], sentinel: Bot | None = None, sentinel_ids: list[int] | None = None) -> None:
        self.primary, self.audit, self.admin_ids = primary, audit, admin_ids
        self.sentinel, self.sentinel_ids = sentinel, sentinel_ids or []
        self.last_sent: dict[str, datetime] = {}

    async def send(self, key: str, text: str, *, bot_id: int | None, severity: str) -> None:
        now = datetime.now(UTC)
        if key in self.last_sent and now - self.last_sent[key] < timedelta(minutes=10):
            return
        self.last_sent[key] = now
        logger.error("Telegram security alert: %s (%s)", key, severity)
        delivered = False
        targets = [(self.sentinel, self.sentinel_ids), (self.primary, self.admin_ids)]
        for client, ids in targets:
            if client is None:
                continue
            for chat_id in ids:
                try:
                    await client.send_message(chat_id, text)
                    delivered = True
                except Exception as exc:  # Telegram errors can contain request URLs; record class only.
                    self.audit.write("security_alert_failed", severity="ERROR", result="failed", bot_id=bot_id, channel="sentinel" if client is self.sentinel else "primary", **safe_error(exc))
        self.audit.write("security_alert_sent" if delivered else "security_alert_failed", severity=severity, result="sent" if delivered else "unavailable", bot_id=bot_id)


class TelegramSecurityMonitor:
    def __init__(self, bot: Bot, config: AppYamlConfig, audit: JsonlAudit, state: SecurityState, alerts: SecurityAlerts) -> None:
        self.bot, self.config, self.audit, self.state, self.alerts = bot, config, audit, state, alerts
        self.bot_id: int | None = None
        self.username: str | None = None
        self.webhook_detections: deque[datetime] = deque()

    async def check(self, *, startup: bool = False) -> None:
        baseline = self.config.telegram_security
        me = await self.bot.get_me()
        self.bot_id, self.username = me.id, me.username
        if baseline.expected_bot_id is None:
            raise SecurityViolation("telegram_security.expected_bot_id must be configured")
        if me.id != baseline.expected_bot_id or (baseline.expected_username and me.username.lower() != baseline.expected_username.lstrip("@").lower()):
            self.audit.write("token_identity_mismatch", severity="CRITICAL", result="rejected", bot_id=me.id, actual_username=me.username)
            raise SecurityViolation("Telegram bot identity does not match configured baseline")
        self.audit.write("token_identity_verified", bot_id=me.id, actual_username=me.username)
        await self._check_webhook()
        await self._check_profile(me)
        now = utc_now()
        baseline_fingerprint = hashlib.sha256(self.config.telegram_security.model_dump_json().encode()).hexdigest()[:12]
        self.state.update(last_successful_security_check=now, last_known_empty_webhook_check=now, git_revision=git_revision(), token_fingerprint=self.audit.token_fingerprint, profile_baseline_fingerprint=baseline_fingerprint)

    async def _check_webhook(self) -> None:
        info = await self.bot.get_webhook_info()
        if not info.url:
            return
        metadata = webhook_metadata(info)
        now = datetime.now(UTC)
        self.webhook_detections.append(now)
        while self.webhook_detections and now - self.webhook_detections[0] > timedelta(minutes=10):
            self.webhook_detections.popleft()
        severity = "CRITICAL" if len(self.webhook_detections) >= 2 else "ERROR"
        self.audit.write("unauthorized_webhook_detected", severity=severity, result="detected", bot_id=self.bot_id, **metadata)
        self.state.update(webhook_detected_at=utc_now(), pending_count_before_deletion=info.pending_update_count, webhook_hostname=metadata["webhook_hostname"], webhook_port=metadata["webhook_port"])
        alert = f"{severity} unauthorized_webhook_detected UTC={utc_now()} bot={self.bot_id}/@{self.username} host={metadata['webhook_hostname']}:{metadata['webhook_port']} recovery=pending. Rotate token via BotFather immediately."
        await self.alerts.send("unauthorized_webhook", alert, bot_id=self.bot_id, severity=severity)
        try:
            await self.bot.delete_webhook(drop_pending_updates=False)
            after = await self.bot.get_webhook_info()
            if after.url:
                raise SecurityViolation("Webhook remains active after deletion")
        except Exception as exc:
            self.audit.write("unauthorized_webhook_delete_failed", severity="CRITICAL", result="failed", bot_id=self.bot_id, **safe_error(exc), **metadata)
            await self.alerts.send("webhook_recovery_failed", alert.replace("recovery=pending", "recovery=FAILED"), bot_id=self.bot_id, severity="CRITICAL")
            raise SecurityViolation("Unable to restore safe polling state") from None
        removed = utc_now()
        self.audit.write("unauthorized_webhook_deleted", severity=severity, result="auto_recovered", bot_id=self.bot_id, drop_pending_updates=False, **metadata)
        self.state.update(webhook_removed_at=removed)

    async def _check_profile(self, me: Any) -> None:
        b = self.config.telegram_security
        actual: dict[str, Any] = {"display_name": (await self.bot.get_my_name()).name}
        if b.expected_description is not None:
            actual["description"] = (await self.bot.get_my_description()).description
        if b.expected_short_description is not None:
            actual["short_description"] = (await self.bot.get_my_short_description()).short_description
        if b.expected_commands is not None:
            actual["commands"] = [(x.command, x.description) for x in await self.bot.get_my_commands()]
        expected: dict[str, Any] = {"display_name": b.expected_display_name}
        if b.expected_description is not None: expected["description"] = b.expected_description
        if b.expected_short_description is not None: expected["short_description"] = b.expected_short_description
        if b.expected_commands is not None: expected["commands"] = [(x.command, x.description) for x in b.expected_commands]
        mismatches = {
            key: {
                "expected_fingerprint": hashlib.sha256(repr(expected[key]).encode()).hexdigest()[:12],
                "actual_fingerprint": hashlib.sha256(repr(value).encode()).hexdigest()[:12],
            }
            for key, value in actual.items() if expected.get(key) is not None and expected[key] != value
        }
        if not mismatches:
            return
        self.audit.write("bot_profile_mismatch", severity="ERROR", result="detected", bot_id=me.id, mismatches=mismatches)
        self.state.update(profile_mismatch_detected_at=utc_now(), profile_mismatch_fields=list(mismatches))
        await self.alerts.send("bot_profile_mismatch", f"ERROR bot_profile_mismatch UTC={utc_now()} bot={me.id}/@{me.username}. Rotate token via BotFather immediately.", bot_id=me.id, severity="ERROR")
        if not b.restore_profile:
            return
        try:
            if "display_name" in mismatches: await self.bot.set_my_name(name=b.expected_display_name)
            if "description" in mismatches: await self.bot.set_my_description(description=b.expected_description)
            if "short_description" in mismatches: await self.bot.set_my_short_description(short_description=b.expected_short_description)
            if "commands" in mismatches: await self.bot.set_my_commands(commands=[BotCommand(command=x.command, description=x.description) for x in b.expected_commands or []])
            self.audit.write("bot_profile_restored", severity="ERROR", result="auto_recovered", bot_id=me.id, fields=list(mismatches))
        except Exception as exc:
            self.audit.write("bot_profile_restore_failed", severity="CRITICAL", result="failed", bot_id=me.id, fields=list(mismatches), **safe_error(exc))

    async def run_forever(self) -> None:
        self.audit.write("security_monitor_started", bot_id=self.bot_id)
        while True:
            await asyncio.sleep(self.config.telegram_security.monitor_interval_seconds)
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.audit.write("security_check_failed", severity="CRITICAL", result="failed", bot_id=self.bot_id, **safe_error(exc))

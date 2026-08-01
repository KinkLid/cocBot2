from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.types import BotCommand

from app.config.settings import AppYamlConfig
from app.security.audit import JsonlAudit, SecurityState, git_revision, utc_now

logger = logging.getLogger("security")


class SecurityViolation(RuntimeError):
    """The process must not continue polling in the current security state."""


def safe_error(exc: BaseException) -> dict[str, str]:
    return {"error_class": type(exc).__name__}


def webhook_metadata(info: Any) -> dict[str, Any]:
    parsed = urlsplit(info.url)
    return {
        "webhook_scheme": parsed.scheme or None,
        "webhook_hostname": parsed.hostname,
        "webhook_port": parsed.port,
        "webhook_url_fingerprint": hashlib.sha256(info.url.encode()).hexdigest()[:12],
        "pending_update_count": info.pending_update_count,
        "last_error_date": str(info.last_error_date) if info.last_error_date else None,
        "last_error_message_fingerprint": (
            hashlib.sha256(info.last_error_message.encode()).hexdigest()[:12]
            if info.last_error_message
            else None
        ),
        "last_error_message_length": len(info.last_error_message) if info.last_error_message else 0,
        "max_connections": info.max_connections,
        "allowed_updates": [str(value) for value in info.allowed_updates] if info.allowed_updates else None,
    }


class SecurityAlerts:
    def __init__(
        self,
        primary: Bot,
        audit: JsonlAudit,
        admin_ids: list[int],
        sentinel: Bot | None = None,
        sentinel_ids: list[int] | None = None,
        state: SecurityState | None = None,
    ) -> None:
        self.primary = primary
        self.audit = audit
        self.admin_ids = admin_ids
        self.sentinel = sentinel
        self.sentinel_ids = sentinel_ids or []
        self.state = state
        self.last_sent: dict[str, tuple[datetime, int]] = {}

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"INFO": 10, "WARNING": 20, "ERROR": 30, "CRITICAL": 40}.get(severity.upper(), 0)

    def _audit_best_effort(self, event_type: str, **fields: Any) -> None:
        try:
            self.audit.write(event_type, **fields)
        except Exception:
            logger.exception("Unable to write security alert audit event: %s", event_type)

    async def send(self, key: str, text: str, *, bot_id: int | None, severity: str) -> bool:
        now = datetime.now(UTC)
        rank = self._severity_rank(severity)
        state_dedupe_applied = False
        if self.state is not None:
            try:
                state_dedupe_applied = True
                if not self.state.should_send_alert(key, severity_rank=rank, sent_at=now.isoformat()):
                    return False
            except Exception as exc:
                state_dedupe_applied = False
                logger.exception("Persistent security alert deduplication failed")
                self._audit_best_effort(
                    "security_alert_dedupe_failed",
                    severity="ERROR",
                    result="fallback_to_memory",
                    bot_id=bot_id,
                    alert_key=key,
                    **safe_error(exc),
                )
        if not state_dedupe_applied:
            previous = self.last_sent.get(key)
            if previous and now - previous[0] < timedelta(minutes=10) and rank <= previous[1]:
                return False
            self.last_sent[key] = (now, rank)
        logger.error("Telegram security alert: %s (%s)", key, severity)
        delivered = False
        targets = [(self.sentinel, self.sentinel_ids, "sentinel"), (self.primary, self.admin_ids, "primary")]
        for client, ids, channel in targets:
            if client is None:
                continue
            for chat_id in ids:
                try:
                    await client.send_message(chat_id, text)
                    delivered = True
                except Exception as exc:
                    self._audit_best_effort(
                        "security_alert_failed",
                        severity="ERROR",
                        result="failed",
                        bot_id=bot_id,
                        channel=channel,
                        **safe_error(exc),
                    )
        self._audit_best_effort(
            "security_alert_sent" if delivered else "security_alert_failed",
            severity=severity,
            result="sent" if delivered else "unavailable",
            bot_id=bot_id,
            alert_key=key,
        )
        return delivered


class TelegramSecurityMonitor:
    def _audit(self, event_type: str, **fields: Any) -> dict[str, Any] | None:
        try:
            return self.audit.write(event_type, **fields)
        except Exception:
            logger.exception("Unable to write Telegram security audit event: %s", event_type)
            return None

    def __init__(
        self,
        bot: Bot,
        config: AppYamlConfig,
        audit: JsonlAudit,
        state: SecurityState,
        alerts: SecurityAlerts,
    ) -> None:
        self.bot = bot
        self.config = config
        self.audit = audit
        self.state = state
        self.alerts = alerts
        self.bot_id: int | None = None
        self.username: str | None = None
        self._baseline_warning_sent = False

    async def check(self, *, startup: bool = False) -> None:
        baseline = self.config.telegram_security
        me = await self.bot.get_me()
        self.bot_id, self.username = me.id, me.username

        if baseline.expected_bot_id is None:
            if not self._baseline_warning_sent:
                self._audit(
                    "security_baseline_incomplete",
                    severity="CRITICAL" if baseline.require_identity_baseline else "WARNING",
                    result="identity_check_skipped",
                    bot_id=me.id,
                    actual_username=me.username,
                )
                await self.alerts.send(
                    "security_baseline_incomplete",
                    (
                        f"WARNING security_baseline_incomplete UTC={utc_now()} "
                        f"bot={me.id}/@{me.username}. Configure expected_bot_id and expected_username."
                    ),
                    bot_id=me.id,
                    severity="WARNING",
                )
                self._baseline_warning_sent = True
            if baseline.require_identity_baseline:
                raise SecurityViolation("telegram_security.expected_bot_id must be configured")
        else:
            username_mismatch = bool(
                baseline.expected_username
                and (me.username or "").lower() != baseline.expected_username.lstrip("@").lower()
            )
            if me.id != baseline.expected_bot_id or username_mismatch:
                self._audit(
                    "token_identity_mismatch",
                    severity="CRITICAL",
                    result="rejected",
                    bot_id=me.id,
                    actual_username=me.username,
                )
                await self.alerts.send(
                    "token_identity_mismatch",
                    f"CRITICAL token_identity_mismatch UTC={utc_now()} bot={me.id}/@{me.username}.",
                    bot_id=me.id,
                    severity="CRITICAL",
                )
                raise SecurityViolation("Telegram bot identity does not match configured baseline")
            self._audit("token_identity_verified", bot_id=me.id, actual_username=me.username)

        await self._check_webhook()
        await self._check_profile(me)
        now = utc_now()
        baseline_fingerprint = hashlib.sha256(baseline.model_dump_json().encode()).hexdigest()[:12]
        try:
            self.state.update(
                last_successful_security_check=now,
                last_known_empty_webhook_check=now,
                git_revision=git_revision(),
                token_fingerprint=self.audit.token_fingerprint,
                profile_baseline_fingerprint=baseline_fingerprint,
                observed_bot_id=me.id,
                observed_username=me.username,
            )
        except Exception as exc:
            logger.exception("Unable to persist successful security heartbeat")
            self._audit(
                "security_state_write_failed",
                severity="ERROR",
                result="heartbeat_state_unavailable",
                bot_id=me.id,
                **safe_error(exc),
            )

    async def _check_webhook(self) -> None:
        info = await self.bot.get_webhook_info()
        if not info.url:
            return

        metadata = webhook_metadata(info)
        detected_at = utc_now()
        try:
            incident = self.state.begin_webhook_incident(
                detected_at=detected_at,
                pending_count_before_deletion=info.pending_update_count,
                webhook_hostname=metadata["webhook_hostname"],
                webhook_port=metadata["webhook_port"],
                webhook_scheme=metadata["webhook_scheme"],
                webhook_url_fingerprint=metadata["webhook_url_fingerprint"],
                bot_id=self.bot_id,
                username=self.username,
            )
        except Exception as exc:
            logger.exception("Unable to persist webhook incident state; recovery will still be attempted")
            incident = {
                "incident_id": str(uuid.uuid4()),
                "last_known_empty_before_incident": None,
                "detections_in_10_minutes": 1,
            }
            self._audit(
                "security_state_write_failed",
                severity="CRITICAL",
                result="webhook_incident_state_unavailable",
                bot_id=self.bot_id,
                **safe_error(exc),
            )
        incident_id = incident["incident_id"]
        repeat_count = int(incident.get("detections_in_10_minutes", 1))
        severity = "CRITICAL" if repeat_count >= 2 else "ERROR"

        self._audit(
            "unauthorized_webhook_detected",
            severity=severity,
            result="detected",
            bot_id=self.bot_id,
            incident_id=incident_id,
            detections_in_10_minutes=repeat_count,
            last_known_empty_before_incident=incident.get("last_known_empty_before_incident"),
            **metadata,
        )
        alert = (
            f"{severity} unauthorized_webhook_detected UTC={detected_at} "
            f"bot={self.bot_id}/@{self.username} "
            f"host={metadata['webhook_hostname']}:{metadata['webhook_port']} "
            "recovery=pending. Rotate token via BotFather immediately."
        )
        await self.alerts.send("unauthorized_webhook", alert, bot_id=self.bot_id, severity=severity)

        try:
            await self.bot.delete_webhook(drop_pending_updates=False)
            after = await self.bot.get_webhook_info()
            if after.url:
                raise SecurityViolation("Webhook remains active after deletion")
        except Exception as exc:
            try:
                self.state.mark_webhook_recovery_failed(incident_id)
            except Exception:
                logger.exception("Unable to persist failed webhook recovery state")
            self._audit(
                "unauthorized_webhook_delete_failed",
                severity="CRITICAL",
                result="failed",
                bot_id=self.bot_id,
                incident_id=incident_id,
                **safe_error(exc),
                **metadata,
            )
            await self.alerts.send(
                "webhook_recovery_failed",
                alert.replace(severity, "CRITICAL", 1).replace("recovery=pending", "recovery=FAILED"),
                bot_id=self.bot_id,
                severity="CRITICAL",
            )
            raise SecurityViolation("Unable to restore safe polling state") from None

        removed_at = utc_now()
        try:
            self.state.mark_webhook_removed(incident_id, removed_at=removed_at)
        except Exception:
            logger.exception("Unable to persist successful webhook recovery state")
        self._audit(
            "unauthorized_webhook_deleted",
            severity=severity,
            result="auto_recovered",
            bot_id=self.bot_id,
            incident_id=incident_id,
            drop_pending_updates=False,
            removed_at=removed_at,
            **metadata,
        )

    async def _check_profile(self, me: Any) -> None:
        baseline = self.config.telegram_security
        actual: dict[str, Any] = {}
        expected: dict[str, Any] = {}

        if baseline.expected_display_name is not None:
            actual["display_name"] = (await self.bot.get_my_name()).name
            expected["display_name"] = baseline.expected_display_name
        if baseline.expected_description is not None:
            actual["description"] = (await self.bot.get_my_description()).description
            expected["description"] = baseline.expected_description
        if baseline.expected_short_description is not None:
            actual["short_description"] = (await self.bot.get_my_short_description()).short_description
            expected["short_description"] = baseline.expected_short_description
        if baseline.expected_commands is not None:
            actual["commands"] = [(item.command, item.description) for item in await self.bot.get_my_commands()]
            expected["commands"] = [(item.command, item.description) for item in baseline.expected_commands]

        mismatches = {
            key: {
                "expected_fingerprint": hashlib.sha256(repr(expected[key]).encode()).hexdigest()[:12],
                "actual_fingerprint": hashlib.sha256(repr(value).encode()).hexdigest()[:12],
            }
            for key, value in actual.items()
            if expected[key] != value
        }
        if not mismatches:
            return

        self._audit(
            "bot_profile_mismatch",
            severity="ERROR",
            result="detected",
            bot_id=me.id,
            mismatches=mismatches,
        )
        try:
            self.state.update(profile_mismatch_detected_at=utc_now(), profile_mismatch_fields=list(mismatches))
        except Exception:
            logger.exception("Unable to persist profile mismatch state")
        await self.alerts.send(
            "bot_profile_mismatch",
            f"ERROR bot_profile_mismatch UTC={utc_now()} bot={me.id}/@{me.username}. Rotate token via BotFather immediately.",
            bot_id=me.id,
            severity="ERROR",
        )
        if not baseline.restore_profile:
            return

        try:
            if "display_name" in mismatches:
                await self.bot.set_my_name(name=baseline.expected_display_name)
            if "description" in mismatches:
                await self.bot.set_my_description(description=baseline.expected_description)
            if "short_description" in mismatches:
                await self.bot.set_my_short_description(short_description=baseline.expected_short_description)
            if "commands" in mismatches:
                commands = [
                    BotCommand(command=item.command, description=item.description)
                    for item in baseline.expected_commands or []
                ]
                await self.bot.set_my_commands(commands=commands)
            self._audit(
                "bot_profile_restored",
                severity="ERROR",
                result="auto_recovered",
                bot_id=me.id,
                fields=list(mismatches),
            )
        except Exception as exc:
            self._audit(
                "bot_profile_restore_failed",
                severity="CRITICAL",
                result="failed",
                bot_id=me.id,
                fields=list(mismatches),
                **safe_error(exc),
            )
            await self.alerts.send(
                "bot_profile_restore_failed",
                f"CRITICAL bot_profile_restore_failed UTC={utc_now()} bot={me.id}/@{me.username}.",
                bot_id=me.id,
                severity="CRITICAL",
            )

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
            except Exception as exc:
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

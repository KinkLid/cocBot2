from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config.settings import AppYamlConfig
from app.security.audit import JsonlAudit, SecurityState
from app.security.monitor import SecurityAlerts, SecurityViolation, TelegramSecurityMonitor


class FakeBot:
    def __init__(self, webhook_url="", *, bot_id=42, username="safe_bot", name="Safe Bot"):
        self.webhook_url = webhook_url
        self.bot_id = bot_id
        self.username = username
        self.name = name
        self.delete_calls: list[bool] = []
        self.send_message = AsyncMock()
        self.fail_delete = False
        self.set_my_name = AsyncMock(side_effect=self._set_name)

    async def _set_name(self, name=None, **_kwargs):
        self.name = name
        return True

    async def get_me(self):
        return SimpleNamespace(id=self.bot_id, username=self.username, first_name=self.name)

    async def get_my_name(self):
        return SimpleNamespace(name=self.name)

    async def get_webhook_info(self):
        return SimpleNamespace(
            url=self.webhook_url,
            pending_update_count=14,
            last_error_date=None,
            last_error_message=None,
            max_connections=40,
            allowed_updates=["message"],
        )

    async def delete_webhook(self, *, drop_pending_updates):
        self.delete_calls.append(drop_pending_updates)
        if self.fail_delete:
            raise RuntimeError("secret URL must not escape")
        self.webhook_url = ""
        return True


def config(**security):
    values = {
        "expected_bot_id": 42,
        "expected_username": "safe_bot",
        "expected_display_name": "Safe Bot",
    }
    values.update(security)
    return AppYamlConfig.model_validate({"main_clan_tag": "#A", "telegram_security": values})


def setup(tmp_path, bot, cfg=None, admin_ids=None):
    audit = JsonlAudit(tmp_path / "security.jsonl", "fake-token-for-fingerprint")
    state = SecurityState(tmp_path / "state.json")
    alerts = SecurityAlerts(bot, audit, admin_ids or [])
    return TelegramSecurityMonitor(bot, cfg or config(), audit, state, alerts), audit, state


@pytest.mark.asyncio
async def test_empty_webhook_changes_nothing(tmp_path):
    bot = FakeBot()
    monitor, _, _ = setup(tmp_path, bot)
    await monitor.check(startup=True)
    assert bot.delete_calls == []


@pytest.mark.asyncio
async def test_missing_identity_baseline_is_backward_compatible_but_audited(tmp_path):
    cfg = config(expected_bot_id=None, expected_username=None)
    bot = FakeBot()
    monitor, audit, _ = setup(tmp_path, bot, cfg)
    await monitor.check(startup=True)
    assert "security_baseline_incomplete" in audit.path.read_text()


@pytest.mark.asyncio
async def test_strict_missing_identity_baseline_is_rejected(tmp_path):
    cfg = config(expected_bot_id=None, expected_username=None, require_identity_baseline=True)
    monitor, _, _ = setup(tmp_path, FakeBot(), cfg)
    with pytest.raises(SecurityViolation):
        await monitor.check(startup=True)


@pytest.mark.asyncio
async def test_webhook_evidence_is_sanitized_and_pending_updates_preserved(tmp_path):
    secret_url = "https://attacker.example:8443/a-very-secret-path"
    bot = FakeBot(secret_url)
    monitor, audit, state = setup(tmp_path, bot)
    state.update(last_known_empty_webhook_check="2026-08-01T10:00:00+00:00")
    await monitor.check()
    content = audit.path.read_text()
    assert secret_url not in content and "a-very-secret-path" not in content
    assert "attacker.example" in content
    assert bot.delete_calls == [False] and bot.webhook_url == ""
    incident = state.read()["incidents"][-1]
    assert incident["pending_count_before_deletion"] == 14
    assert incident["last_known_empty_before_incident"] == "2026-08-01T10:00:00+00:00"
    assert incident["detected_at"] <= incident["removed_at"]
    assert state.read()["last_known_empty_webhook_check"] >= incident["removed_at"]


@pytest.mark.asyncio
async def test_webhook_delete_failure_aborts_without_leaking_exception(tmp_path):
    bot = FakeBot("https://attacker.example/private")
    bot.fail_delete = True
    monitor, audit, state = setup(tmp_path, bot)
    with pytest.raises(SecurityViolation):
        await monitor.check()
    content = audit.path.read_text()
    assert "/private" not in content and "secret URL" not in content
    assert "unauthorized_webhook_delete_failed" in content
    assert state.read()["incidents"][-1]["status"] == "recovery_failed"


@pytest.mark.asyncio
async def test_identity_mismatch_is_rejected(tmp_path):
    monitor, audit, _ = setup(tmp_path, FakeBot(bot_id=99))
    with pytest.raises(SecurityViolation):
        await monitor.check(startup=True)
    assert "token_identity_mismatch" in audit.path.read_text()


@pytest.mark.asyncio
async def test_profile_mismatch_restore_policy(tmp_path):
    bot = FakeBot(name="Changed")
    monitor, audit, _ = setup(tmp_path, bot, config(restore_profile=False))
    await monitor.check()
    bot.set_my_name.assert_not_awaited()
    assert "bot_profile_mismatch" in audit.path.read_text()

    bot2 = FakeBot(name="Changed")
    monitor2, _, _ = setup(tmp_path / "two", bot2, config(restore_profile=True))
    await monitor2.check()
    bot2.set_my_name.assert_awaited_once_with(name="Safe Bot")


@pytest.mark.asyncio
async def test_alert_rate_limit_allows_severity_escalation(tmp_path):
    bot = FakeBot()
    _, audit, _ = setup(tmp_path, bot)
    alerts = SecurityAlerts(bot, audit, [123])
    assert await alerts.send("same", "safe", bot_id=42, severity="ERROR") is True
    assert await alerts.send("same", "safe", bot_id=42, severity="ERROR") is False
    assert await alerts.send("same", "critical", bot_id=42, severity="CRITICAL") is True
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_repeated_webhook_is_critical_and_creates_separate_incident(tmp_path):
    bot = FakeBot("https://one.example/hook")
    monitor, audit, state = setup(tmp_path, bot, admin_ids=[123])
    await monitor.check()
    state.record_received_update(100, received_at="2026-08-01T10:01:00+00:00")

    bot.webhook_url = "https://two.example/hook"
    await monitor.check()
    incidents = state.read()["incidents"]
    assert len(incidents) == 2
    assert incidents[0]["first_recovered_update"]["update_id"] == 100
    assert incidents[1]["first_recovered_update"] is None
    events = [json.loads(line) for line in audit.path.read_text().splitlines()]
    detected = [event for event in events if event["event_type"] == "unauthorized_webhook_detected"]
    assert [event["severity"] for event in detected] == ["ERROR", "CRITICAL"]
    assert bot.send_message.await_count >= 2


@pytest.mark.asyncio
async def test_alert_rate_limit_persists_across_alert_instances(tmp_path):
    bot = FakeBot()
    audit = JsonlAudit(tmp_path / "security.jsonl", "token")
    state = SecurityState(tmp_path / "state.json")
    first = SecurityAlerts(bot, audit, [123], state=state)
    second = SecurityAlerts(bot, audit, [123], state=state)
    assert await first.send("persistent", "error", bot_id=42, severity="ERROR") is True
    assert await second.send("persistent", "same", bot_id=42, severity="ERROR") is False
    assert await second.send("persistent", "critical", bot_id=42, severity="CRITICAL") is True
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_state_failure_does_not_prevent_webhook_recovery(tmp_path):
    class FailingState:
        def begin_webhook_incident(self, **_kwargs):
            raise OSError("disk unavailable")

        def mark_webhook_removed(self, *_args, **_kwargs):
            raise OSError("disk unavailable")

        def update(self, **_kwargs):
            raise OSError("disk unavailable")

    bot = FakeBot("https://attacker.example/private")
    audit = JsonlAudit(tmp_path / "security.jsonl", "token")
    alerts = SecurityAlerts(bot, audit, [])
    monitor = TelegramSecurityMonitor(bot, config(), audit, FailingState(), alerts)
    await monitor.check()
    assert bot.delete_calls == [False]
    assert bot.webhook_url == ""
    assert "security_state_write_failed" in audit.path.read_text()


def test_hash_chain_survives_multiple_writers_and_restart(tmp_path):
    path = tmp_path / "security.jsonl"
    first = JsonlAudit(path, "token")
    second = JsonlAudit(path, "token")
    first.write("one")
    second.write("two")
    JsonlAudit(path, "token").write("three")
    events = [json.loads(line) for line in path.read_text().splitlines()]
    previous = ""
    for event in events:
        assert event["previous_event_hash"] == previous
        body = dict(event)
        actual = body.pop("event_hash")
        assert actual == JsonlAudit.calculate_event_hash(body)
        previous = actual


def test_state_is_atomic_private_and_update_ids_are_monotonic(tmp_path):
    state = SecurityState(tmp_path / "state.json")
    state.update(value=1)
    state.update(other=2)
    state.record_received_update(11, received_at="2026-08-01T10:00:01+00:00")
    state.record_received_update(10, received_at="2026-08-01T10:00:02+00:00")
    state.record_completed_update(11, completed_at="2026-08-01T10:00:03+00:00", handled=True, success=True)
    state.record_completed_update(10, completed_at="2026-08-01T10:00:04+00:00", handled=True, success=True)
    value = state.read()
    assert value["max_received_update_id"] == 11
    assert value["max_completed_update_id"] == 11
    assert value["last_processed_update_id"] == 11
    assert state.path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))

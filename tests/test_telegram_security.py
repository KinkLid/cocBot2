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
        self.webhook_url, self.bot_id, self.username, self.name = webhook_url, bot_id, username, name
        self.delete_calls = []
        self.send_message = AsyncMock()
        self.fail_delete = False
        self.set_my_name = AsyncMock(side_effect=self._set_name)

    async def _set_name(self, name=None, **_kwargs): self.name = name; return True
    async def get_me(self): return SimpleNamespace(id=self.bot_id, username=self.username, first_name=self.name)
    async def get_my_name(self): return SimpleNamespace(name=self.name)
    async def get_webhook_info(self):
        return SimpleNamespace(url=self.webhook_url, pending_update_count=14, last_error_date=None, last_error_message=None, max_connections=40, allowed_updates=["message"])
    async def delete_webhook(self, *, drop_pending_updates):
        self.delete_calls.append(drop_pending_updates)
        if self.fail_delete: raise RuntimeError("secret URL must not escape")
        self.webhook_url = ""; return True


def config(**security):
    values = {"expected_bot_id": 42, "expected_username": "safe_bot", "expected_display_name": "Safe Bot"}
    values.update(security)
    return AppYamlConfig.model_validate({"main_clan_tag": "#A", "telegram_security": values})


def setup(tmp_path, bot, cfg=None):
    audit = JsonlAudit(tmp_path / "security.jsonl", "fake-token-for-fingerprint")
    state = SecurityState(tmp_path / "state.json")
    alerts = SecurityAlerts(bot, audit, [])
    return TelegramSecurityMonitor(bot, cfg or config(), audit, state, alerts), audit, state


@pytest.mark.asyncio
async def test_empty_webhook_changes_nothing(tmp_path):
    bot = FakeBot(); monitor, _, _ = setup(tmp_path, bot)
    await monitor.check(startup=True)
    assert bot.delete_calls == []


@pytest.mark.asyncio
async def test_webhook_evidence_is_sanitized_and_pending_updates_preserved(tmp_path):
    secret_url = "https://attacker.example:8443/a-very-secret-path"
    bot = FakeBot(secret_url); monitor, audit, state = setup(tmp_path, bot)
    await monitor.check()
    content = audit.path.read_text()
    assert secret_url not in content and "a-very-secret-path" not in content
    assert "attacker.example" in content
    assert bot.delete_calls == [False] and bot.webhook_url == ""
    assert state.read()["pending_count_before_deletion"] == 14


@pytest.mark.asyncio
async def test_webhook_delete_failure_aborts_without_leaking_exception(tmp_path):
    bot = FakeBot("https://attacker.example/private"); bot.fail_delete = True
    monitor, audit, _ = setup(tmp_path, bot)
    with pytest.raises(SecurityViolation): await monitor.check()
    content = audit.path.read_text()
    assert "/private" not in content and "secret URL" not in content
    assert "unauthorized_webhook_delete_failed" in content


@pytest.mark.asyncio
async def test_identity_mismatch_is_rejected(tmp_path):
    monitor, audit, _ = setup(tmp_path, FakeBot(bot_id=99))
    with pytest.raises(SecurityViolation): await monitor.check(startup=True)
    assert "token_identity_mismatch" in audit.path.read_text()


@pytest.mark.asyncio
async def test_profile_mismatch_restore_policy(tmp_path):
    bot = FakeBot(name="Changed"); monitor, audit, _ = setup(tmp_path, bot, config(restore_profile=False))
    await monitor.check(); bot.set_my_name.assert_not_awaited()
    assert "bot_profile_mismatch" in audit.path.read_text()
    bot2 = FakeBot(name="Changed"); monitor2, _, _ = setup(tmp_path / "two", bot2, config(restore_profile=True))
    await monitor2.check(); bot2.set_my_name.assert_awaited_once_with(name="Safe Bot")


@pytest.mark.asyncio
async def test_alert_rate_limit_and_unavailable_channel(tmp_path):
    bot = FakeBot(); _, audit, _ = setup(tmp_path, bot)
    alerts = SecurityAlerts(bot, audit, [])
    await alerts.send("same", "safe", bot_id=42, severity="ERROR")
    await alerts.send("same", "safe", bot_id=42, severity="ERROR")
    lines = [json.loads(x) for x in audit.path.read_text().splitlines()]
    assert sum(x["event_type"] == "security_alert_failed" for x in lines) == 1


def test_state_is_atomic_and_files_are_private(tmp_path):
    state = SecurityState(tmp_path / "state.json"); state.update(value=1); state.update(other=2)
    assert state.read() == {"value": 1, "other": 2}
    assert state.path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))

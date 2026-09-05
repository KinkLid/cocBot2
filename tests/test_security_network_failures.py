from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError

from app.config.settings import AppYamlConfig
from app.security.audit import JsonlAudit, SecurityState
from app.security.monitor import SecurityAlerts, SecurityViolation, TelegramSecurityMonitor
from app.security.resilient_monitor import ResilientTelegramSecurityMonitor


class GetWebhookInfo:
    pass


class FakeBot:
    def __init__(self) -> None:
        self.send_message = AsyncMock()


def make_monitor(tmp_path):
    bot = FakeBot()
    config = AppYamlConfig.model_validate(
        {
            "main_clan_tag": "#A",
            "telegram_security": {
                "expected_bot_id": 42,
                "expected_username": "safe_bot",
            },
        }
    )
    audit = JsonlAudit(tmp_path / "security.jsonl", "fake-token")
    state = SecurityState(tmp_path / "state.json")
    alerts = SecurityAlerts(bot, audit, [123])
    monitor = ResilientTelegramSecurityMonitor(bot, config, audit, state, alerts)
    monitor.bot_id = 42
    monitor.username = "safe_bot"
    return monitor, bot, audit


def network_error() -> TelegramNetworkError:
    return TelegramNetworkError(method=GetWebhookInfo(), message="temporary network failure")


@pytest.mark.asyncio
async def test_startup_network_failure_retries_until_security_check_succeeds(tmp_path, monkeypatch):
    monitor, bot, audit = make_monitor(tmp_path)
    base_check = AsyncMock(side_effect=[network_error(), None])
    sleep = AsyncMock()
    monkeypatch.setattr(TelegramSecurityMonitor, "check", base_check)
    monkeypatch.setattr("app.security.resilient_monitor.asyncio.sleep", sleep)

    await monitor.check(startup=True)

    assert base_check.await_count == 2
    assert [call.kwargs for call in base_check.await_args_list] == [{"startup": True}, {"startup": True}]
    sleep.assert_awaited_once_with(monitor.config.telegram_security.monitor_interval_seconds)
    bot.send_message.assert_not_awaited()
    events = [json.loads(line) for line in audit.path.read_text().splitlines()]
    assert any(event["event_type"] == "security_check_network_failed" for event in events)
    assert any(event["event_type"] == "security_check_network_recovered" for event in events)


@pytest.mark.asyncio
async def test_startup_security_violation_remains_fatal(tmp_path, monkeypatch):
    monitor, _bot, _audit = make_monitor(tmp_path)
    base_check = AsyncMock(side_effect=SecurityViolation("identity mismatch"))
    sleep = AsyncMock()
    monkeypatch.setattr(TelegramSecurityMonitor, "check", base_check)
    monkeypatch.setattr("app.security.resilient_monitor.asyncio.sleep", sleep)

    with pytest.raises(SecurityViolation, match="identity mismatch"):
        await monitor.check(startup=True)

    base_check.assert_awaited_once_with(startup=True)
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_network_failure_is_audited_without_admin_alert(tmp_path):
    monitor, bot, audit = make_monitor(tmp_path)

    await monitor._handle_network_failure(network_error())

    bot.send_message.assert_not_awaited()
    event = json.loads(audit.path.read_text().splitlines()[-1])
    assert event["event_type"] == "security_check_network_failed"
    assert event["severity"] == "WARNING"
    assert event["result"] == "transient_failure"
    assert event["check_stage"] == "GetWebhookInfo"
    assert event["consecutive_failures"] == 1
    assert event["error_class"] == "TelegramNetworkError"


@pytest.mark.asyncio
async def test_admin_is_alerted_only_after_three_consecutive_network_failures(tmp_path):
    monitor, bot, audit = make_monitor(tmp_path)

    await monitor._handle_network_failure(network_error())
    await monitor._handle_network_failure(network_error())
    bot.send_message.assert_not_awaited()

    await monitor._handle_network_failure(network_error())

    bot.send_message.assert_awaited_once()
    chat_id, text = bot.send_message.await_args.args
    assert chat_id == 123
    assert "Подряд ошибок: 3" in text
    assert "Бот продолжает работу" in text
    events = [json.loads(line) for line in audit.path.read_text().splitlines()]
    failures = [event for event in events if event["event_type"] == "security_check_network_failed"]
    assert [event["consecutive_failures"] for event in failures] == [1, 2, 3]
    assert all(event["severity"] == "WARNING" for event in failures)


@pytest.mark.asyncio
async def test_success_after_alert_sends_recovery_and_resets_counter(tmp_path):
    monitor, bot, audit = make_monitor(tmp_path)
    for _ in range(3):
        await monitor._handle_network_failure(network_error())

    await monitor._handle_successful_check()

    assert bot.send_message.await_count == 2
    recovery_text = bot.send_message.await_args.args[1]
    assert "Соединение с Telegram API восстановлено" in recovery_text
    events = [json.loads(line) for line in audit.path.read_text().splitlines()]
    recovered = [event for event in events if event["event_type"] == "security_check_network_recovered"]
    assert len(recovered) == 1
    assert recovered[0]["previous_consecutive_failures"] == 3
    assert monitor._consecutive_network_failures == 0
    assert monitor._network_failure_alert_delivered is False


@pytest.mark.asyncio
async def test_success_after_one_silent_failure_is_audited_without_recovery_message(tmp_path):
    monitor, bot, audit = make_monitor(tmp_path)

    await monitor._handle_network_failure(network_error())
    await monitor._handle_successful_check()

    bot.send_message.assert_not_awaited()
    events = [json.loads(line) for line in audit.path.read_text().splitlines()]
    assert any(event["event_type"] == "security_check_network_recovered" for event in events)

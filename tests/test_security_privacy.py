from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from app.bot.middlewares.update_audit import UpdateAuditMiddleware
from app.security.audit import JsonlAudit, SecurityState
from scripts import check_server_health, rotate_telegram_token


@pytest.mark.asyncio
async def test_update_audit_never_serializes_message_or_callback_contents(tmp_path):
    audit = JsonlAudit(tmp_path / "updates.jsonl", "fake-token")
    middleware = UpdateAuditMiddleware(audit, SecurityState(tmp_path / "state.json"))
    message = SimpleNamespace(chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=2), text="PRIVATE MESSAGE", callback_data="SECRET CALLBACK")
    update = SimpleNamespace(update_id=10, event_type="message", event=message)
    await middleware(lambda _e, _d: _return_ok(), update, {})
    content = audit.path.read_text()
    assert "PRIVATE MESSAGE" not in content and "SECRET CALLBACK" not in content


async def _return_ok(): return True


def test_health_check_has_no_token_bearing_url_or_urllib():
    source = inspect.getsource(check_server_health)
    assert "api.telegram.org/bot" not in source
    assert "urllib" not in source
    assert "{token}" not in source


def test_rotation_does_not_accept_token_argument():
    source = inspect.getsource(rotate_telegram_token)
    assert 'add_argument("--token"' not in source
    assert "getpass.getpass" in source


def test_registration_audit_source_does_not_log_values():
    from app.bot.handlers import registration
    source = inspect.getsource(registration._registration_audit)
    assert "player_token" not in source and "player_tag" not in source


def test_systemd_has_one_polling_process():
    unit = open("deploy/systemd/cocbot.service.template", encoding="utf-8").read()
    assert unit.count("ExecStart=") == 1
    assert "app.main" in unit and "getUpdates" not in unit

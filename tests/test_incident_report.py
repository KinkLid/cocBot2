from __future__ import annotations

import json

from app.security.audit import JsonlAudit, SecurityState
from scripts.incident_report import (
    load_events,
    registration_summary,
    select_incident,
    update_summary,
    verify_hash_chain,
)


def test_report_uses_incident_specific_window_and_real_evidence(tmp_path):
    state = SecurityState(tmp_path / "state.json")
    state.update(last_known_empty_webhook_check="2026-08-01T10:00:00+00:00")
    incident = state.begin_webhook_incident(
        detected_at="2026-08-01T10:05:00+00:00",
        webhook_hostname="attacker.example",
        webhook_port=8443,
        pending_count_before_deletion=14,
    )
    state.mark_webhook_removed(incident["incident_id"], removed_at="2026-08-01T10:06:00+00:00")
    state.update(last_known_empty_webhook_check="2026-08-01T10:06:01+00:00")

    selected = select_incident(state.read(), None)
    assert selected["last_known_empty_before_incident"] == "2026-08-01T10:00:00+00:00"
    assert selected["detected_at"] == "2026-08-01T10:05:00+00:00"

    security = JsonlAudit(tmp_path / "security.jsonl", "token")
    security.write(
        "waiting_for_player_token",
        telegram_user_id=123,
        timestamp_override="not-used",
    )
    events, errors = load_events(security.path)
    assert not errors
    assert verify_hash_chain(events) == []


def test_report_summaries_do_not_require_message_contents():
    security_events = [
        {
            "timestamp": "2026-08-01T10:03:00+00:00",
            "event_type": "waiting_for_player_token",
            "telegram_user_id": 123,
        },
        {
            "timestamp": "2026-08-01T10:04:00+00:00",
            "event_type": "registration_completed",
            "telegram_user_id": 123,
        },
    ]
    updates = [
        {"received_at": "2026-08-01T09:59:00+00:00", "update_id": 10},
        {"received_at": "2026-08-01T10:03:00+00:00", "update_id": 11},
        {"received_at": "2026-08-01T10:07:00+00:00", "update_id": 12},
    ]
    from scripts.incident_report import parse_time

    start = parse_time("2026-08-01T10:00:00+00:00")
    end = parse_time("2026-08-01T10:06:00+00:00")
    registration = registration_summary(security_events, start, end)
    update = update_summary(updates, start, end)
    assert registration["users_seen_waiting_for_player_token"] == [123]
    assert update == {
        "max_update_before_window": 10,
        "min_update_after_window": 12,
        "updates_processed_by_our_polling_in_window": 1,
    }
    assert "message" not in json.dumps({"registration": registration, "update": update})

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def log_paths(path: Path) -> list[Path]:
    rotated: list[Path] = []
    for candidate in path.parent.glob(path.name + ".*"):
        suffix = candidate.name.removeprefix(path.name + ".")
        if suffix.isdigit():
            rotated.append(candidate)
    rotated.sort(key=lambda item: int(item.name.rsplit(".", 1)[1]), reverse=True)
    return [*rotated, path]


def load_events(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for candidate in log_paths(path):
        if not candidate.exists():
            continue
        for line_number, raw in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                errors.append(f"{candidate}:{line_number}: invalid JSON")
                continue
            if isinstance(event, dict):
                events.append(event)
    return events, errors


def verify_hash_chain(events: list[dict[str, Any]]) -> list[str]:
    from app.security.audit import JsonlAudit

    errors: list[str] = []
    previous = ""
    for index, event in enumerate(events, 1):
        if event.get("hash_version") != JsonlAudit.HASH_VERSION:
            previous = str(event.get("event_hash") or previous)
            continue
        expected_previous = str(event.get("previous_event_hash") or "")
        if expected_previous != previous:
            errors.append(f"event {index}: previous hash mismatch")
        body = dict(event)
        actual_hash = str(body.pop("event_hash", ""))
        expected_hash = JsonlAudit.calculate_event_hash(body)
        if actual_hash != expected_hash:
            errors.append(f"event {index}: event hash mismatch")
        previous = actual_hash
    return errors


def select_incident(state: dict[str, Any], incident_id: str | None) -> dict[str, Any]:
    incidents = [item for item in state.get("incidents", []) if isinstance(item, dict)]
    if incident_id:
        for incident in incidents:
            if incident.get("incident_id") == incident_id:
                return incident
        raise RuntimeError(f"incident not found: {incident_id}")
    if incidents:
        return incidents[-1]
    return {
        "incident_id": state.get("current_incident_id", "legacy-state"),
        "kind": "unauthorized_webhook",
        "status": "unknown",
        "last_known_empty_before_incident": state.get("last_known_empty_before_incident")
        or state.get("last_known_empty_webhook_check"),
        "detected_at": state.get("webhook_detected_at"),
        "removed_at": state.get("webhook_removed_at"),
        "first_recovered_update": state.get("first_recovered_update_after_incident"),
        "pending_count_before_deletion": state.get("pending_count_before_deletion"),
        "webhook_hostname": state.get("webhook_hostname"),
        "webhook_port": state.get("webhook_port"),
    }


def registration_summary(
    events: list[dict[str, Any]], start: datetime | None, end: datetime | None
) -> dict[str, Any]:
    allowed = {
        "registration_started",
        "waiting_for_player_tag",
        "waiting_for_player_token",
        "registration_completed",
        "registration_failed",
        "registration_cancelled",
    }
    users: dict[str, set[int]] = {name: set() for name in allowed}
    for event in events:
        event_type = event.get("event_type")
        timestamp = parse_time(event.get("timestamp"))
        user_id = event.get("telegram_user_id")
        if event_type not in allowed or not isinstance(user_id, int) or timestamp is None:
            continue
        if start and timestamp < start:
            continue
        if end and timestamp > end:
            continue
        users[event_type].add(user_id)
    waiting = users["waiting_for_player_token"]
    return {
        "unique_users_with_registration_events": len(set().union(*users.values())),
        "users_seen_waiting_for_player_token": sorted(waiting),
        "counts": {key: len(value) for key, value in sorted(users.items())},
    }


def update_summary(events: list[dict[str, Any]], start: datetime | None, end: datetime | None) -> dict[str, Any]:
    before: int | None = None
    after: int | None = None
    in_window: list[int] = []
    for event in events:
        update_id = event.get("update_id")
        timestamp = parse_time(event.get("received_at") or event.get("timestamp"))
        if not isinstance(update_id, int) or timestamp is None:
            continue
        if start and timestamp < start:
            before = update_id if before is None else max(before, update_id)
        elif end and timestamp > end:
            after = update_id if after is None else min(after, update_id)
        else:
            in_window.append(update_id)
    return {
        "max_update_before_window": before,
        "min_update_after_window": after,
        "updates_processed_by_our_polling_in_window": len(set(in_window)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a sanitized Telegram incident report")
    parser.add_argument("--state", default="data/security-state.json")
    parser.add_argument("--security-log", default="logs/security-audit.jsonl")
    parser.add_argument("--update-log", default="logs/update-audit.jsonl")
    parser.add_argument("--incident-id")
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        raise RuntimeError(f"state file does not exist: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise RuntimeError("security state must be a JSON object")

    security_events, security_parse_errors = load_events(Path(args.security_log))
    update_events, update_parse_errors = load_events(Path(args.update_log))
    chain_errors = verify_hash_chain(security_events)
    incident = select_incident(state, args.incident_id)
    start = parse_time(incident.get("last_known_empty_before_incident"))
    detected = parse_time(incident.get("detected_at"))
    removed = parse_time(incident.get("removed_at"))
    end = removed or detected

    registrations = registration_summary(security_events, start, end)
    updates = update_summary(update_events, start, end)

    print("# Telegram incident report (sanitized)")
    print(f"Incident ID: {incident.get('incident_id', 'Unknown')}")
    print(f"Confirmed status: {incident.get('status', 'Unknown')}")
    print(f"Confirmed detected at: {incident.get('detected_at', 'Unknown')}")
    print(f"Confirmed removed at: {incident.get('removed_at', 'Unknown')}")
    print(
        "Confirmed last known empty webhook before incident: "
        f"{incident.get('last_known_empty_before_incident', 'Unknown')}"
    )
    print(
        "Likely compromise window: after "
        f"{incident.get('last_known_empty_before_incident', 'Unknown')} "
        f"and by {incident.get('detected_at', 'Unknown')}"
    )
    print(
        "Confirmed sanitized endpoint: "
        f"{incident.get('webhook_hostname', 'Unknown')}:{incident.get('webhook_port', 'Unknown')}"
    )
    print(f"Confirmed pending count at detection: {incident.get('pending_count_before_deletion', 'Unknown')}")
    print(f"First recovered update for this incident: {incident.get('first_recovered_update', 'Unknown')}")
    print(f"Update evidence: {json.dumps(updates, ensure_ascii=False, sort_keys=True)}")
    print(f"Registration evidence: {json.dumps(registrations, ensure_ascii=False, sort_keys=True)}")
    print(f"Security audit records read: {len(security_events)}")
    print(f"Update audit records read: {len(update_events)}")
    print(f"Hash-chain verification errors: {len(chain_errors)}")
    for error in chain_errors[:10]:
        print(f"  - {error}")
    for error in [*security_parse_errors, *update_parse_errors][:10]:
        print(f"Evidence parse warning: {error}")
    print("Potentially affected: updates delivered by Telegram during the likely window.")
    print("Unknown: messages successfully delivered to another webhook.")
    print(
        "Cannot be determined from Telegram Bot API: caller IPs, API call history, "
        "or an exact list/count of intercepted updates."
    )
    print(f"Evidence files: {args.state}, {args.security_log}, {args.update_log}, journald for cocbot")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"incident_report.py: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)

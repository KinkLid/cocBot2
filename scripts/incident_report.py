#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a sanitized Telegram incident report")
    parser.add_argument("--state", default="data/security-state.json")
    parser.add_argument("--security-log", default="logs/security-audit.jsonl")
    parser.add_argument("--update-log", default="logs/update-audit.jsonl")
    args = parser.parse_args()
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    print("# Telegram incident report (sanitized)")
    print(f"Confirmed: detected at: {state.get('webhook_detected_at', 'Unknown')}")
    print(f"Confirmed: removed at: {state.get('webhook_removed_at', 'Unknown')}")
    print(f"Confirmed: last known empty webhook: {state.get('last_known_empty_webhook_check', 'Unknown')}")
    print(f"Likely compromise window: after {state.get('last_known_empty_webhook_check', 'Unknown')} and by {state.get('webhook_detected_at', 'Unknown')}")
    print(f"Confirmed sanitized endpoint: {state.get('webhook_hostname', 'Unknown')}:{state.get('webhook_port', 'Unknown')}")
    print(f"Confirmed pending count at detection: {state.get('pending_count_before_deletion', 'Unknown')}")
    print(f"Confirmed profile mismatch fields: {state.get('profile_mismatch_fields', 'Unknown')}")
    print(f"Last update processed by our polling: {state.get('last_processed_update_id', 'Unknown')} at {state.get('last_processed_update_timestamp', 'Unknown')}")
    print(f"First recovered update after incident: {state.get('first_recovered_update_after_incident', 'Unknown')}")
    print("Potentially affected: updates in the likely window and registration sessions visible in the security audit.")
    print("Unknown: messages successfully delivered to another webhook.")
    print("Cannot be determined from Telegram Bot API: caller IPs, API call history, or an exact list/count of intercepted updates.")
    print(f"Evidence files: {args.state}, {args.security_log}, {args.update_log}, journald for cocbot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Telegram security deployment prerequisites")
    parser.add_argument("--project-dir", default="/opt/cocbot")
    args = parser.parse_args()
    project = Path(args.project_dir).resolve()
    sys.path.insert(0, str(project))

    from app.config.settings import AppYamlConfig

    config_path = Path(os.getenv("CONFIG_PATH", project / "config.yaml"))
    if not config_path.is_absolute():
        config_path = project / config_path
    if not config_path.exists():
        print(f"[security_preflight] ERROR: config file is missing: {config_path}", file=sys.stderr)
        return 1
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = AppYamlConfig.model_validate(raw)
    security = config.telegram_security
    problems: list[str] = []
    warnings: list[str] = []

    if security.require_identity_baseline:
        if security.expected_bot_id is None:
            problems.append("telegram_security.expected_bot_id is required")
        if not security.expected_username:
            problems.append("telegram_security.expected_username is required")
    elif security.expected_bot_id is None:
        warnings.append(
            "identity baseline is incomplete; webhook monitoring remains active but identity verification is skipped"
        )

    paths = (
        os.getenv("SECURITY_AUDIT_FILE", "./logs/security-audit.jsonl"),
        os.getenv("SECURITY_STATE_FILE", "./data/security-state.json"),
        os.getenv("UPDATE_AUDIT_FILE", "./logs/update-audit.jsonl"),
    )
    for value in paths:
        path = Path(value)
        if not path.is_absolute():
            path = project / path
        if not path.parent.exists():
            problems.append(f"security path parent does not exist: {path.parent}")
        elif not os.access(path.parent, os.W_OK):
            problems.append(f"security path parent is not writable by service user: {path.parent}")

    for warning in warnings:
        print(f"[security_preflight] WARNING: {warning}")
    for problem in problems:
        print(f"[security_preflight] ERROR: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

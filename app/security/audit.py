from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, check=True, timeout=2
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class JsonlAudit:
    """Independent, permission-restricted JSONL audit with a best-effort hash chain."""

    def __init__(self, path: str | Path, token: str, *, max_bytes: int = 10_000_000) -> None:
        self.path = Path(path)
        self.token_fingerprint = fingerprint(token)
        self.max_bytes = max_bytes
        self.previous_hash = ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            os.chmod(self.path, 0o600)

    def write(self, event_type: str, *, severity: str = "INFO", result: str = "recorded", bot_id: int | None = None, **metadata: Any) -> dict[str, Any]:
        if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
            rotated = self.path.with_suffix(self.path.suffix + ".1")
            os.replace(self.path, rotated)
            os.chmod(rotated, 0o600)
            self.previous_hash = ""
        event: dict[str, Any] = {
            "timestamp": utc_now(), "event_id": str(uuid.uuid4()), "severity": severity,
            "event_type": event_type, "result": result, "token_fingerprint": self.token_fingerprint,
            "bot_id": bot_id, "process_id": os.getpid(), "git_revision": git_revision(), "hostname": socket.gethostname(),
        }
        event.update(metadata)
        canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        event["previous_event_hash"] = self.previous_hash
        event["event_hash"] = hashlib.sha256((self.previous_hash + canonical).encode()).hexdigest()
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(self.path, 0o600)
        self.previous_hash = event["event_hash"]
        return event


class SecurityState:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def update(self, **values: Any) -> None:
        state = self.read()
        state.update(values)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

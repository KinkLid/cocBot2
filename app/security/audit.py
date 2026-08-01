from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import uuid
from functools import lru_cache
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


@lru_cache(maxsize=1)
def git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.chmod(path, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_last_json_line(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - 131_072))
        lines = stream.read().splitlines()
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None



class JsonlAudit:
    """Permission-restricted JSONL audit safe for multiple writers.

    Every write takes a file lock and obtains the actual last event hash from disk,
    so separate application components and short-lived operator processes cannot
    silently fork the hash chain. The first event after rotation references the
    last event in the rotated file.
    """

    HASH_VERSION = 2

    def __init__(
        self,
        path: str | Path,
        token: str,
        *,
        max_bytes: int = 10_000_000,
        backup_count: int = 3,
    ) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self.token_fingerprint = fingerprint(token)
        self.max_bytes = max_bytes
        self.backup_count = max(1, backup_count)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            os.chmod(self.path, 0o600)

    def _rotated_path(self, index: int) -> Path:
        return self.path.with_suffix(self.path.suffix + f".{index}")

    def _last_hash_locked(self) -> str:
        for candidate in [self.path, *(self._rotated_path(i) for i in range(1, self.backup_count + 1))]:
            event = _read_last_json_line(candidate)
            if event and isinstance(event.get("event_hash"), str):
                return event["event_hash"]
        return ""

    def _rotate_locked(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
            return
        oldest = self._rotated_path(self.backup_count)
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self._rotated_path(index)
            if source.exists():
                os.replace(source, self._rotated_path(index + 1))
        os.replace(self.path, self._rotated_path(1))
        os.chmod(self._rotated_path(1), 0o600)

    @staticmethod
    def calculate_event_hash(event_without_hash: dict[str, Any]) -> str:
        canonical = json.dumps(
            event_without_hash,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def write(
        self,
        event_type: str,
        *,
        severity: str = "INFO",
        result: str = "recorded",
        bot_id: int | None = None,
        **metadata: Any,
    ) -> dict[str, Any]:
        reserved = {
            "timestamp", "event_id", "severity", "event_type", "result",
            "token_fingerprint", "bot_id", "process_id", "git_revision",
            "hostname", "hash_version", "previous_event_hash", "event_hash",
        }
        conflicting = reserved.intersection(metadata)
        if conflicting:
            raise ValueError(f"reserved audit metadata keys: {sorted(conflicting)}")
        with _exclusive_lock(self.lock_path):
            previous_hash = self._last_hash_locked()
            self._rotate_locked()
            event: dict[str, Any] = {
                "timestamp": utc_now(),
                "event_id": str(uuid.uuid4()),
                "severity": severity,
                "event_type": event_type,
                "result": result,
                "token_fingerprint": self.token_fingerprint,
                "bot_id": bot_id,
                "process_id": os.getpid(),
                "git_revision": git_revision(),
                "hostname": socket.gethostname(),
                "hash_version": self.HASH_VERSION,
                "previous_event_hash": previous_hash,
            }
            event.update(metadata)
            event["event_hash"] = self.calculate_event_hash(event)
            line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(self.path, 0o600)
            return event


class SecurityState:
    """Small atomic state file with a separate lock for concurrent tasks/processes."""

    MAX_INCIDENTS = 50

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def read(self) -> dict[str, Any]:
        with _exclusive_lock(self.lock_path):
            return self._read_unlocked()

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
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

    def mutate(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        with _exclusive_lock(self.lock_path):
            state = self._read_unlocked()
            result = mutator(state)
            self._write_unlocked(state)
            return result

    def update(self, **values: Any) -> None:
        self.mutate(lambda state: state.update(values))

    def begin_webhook_incident(self, **metadata: Any) -> dict[str, Any]:
        detected_at = str(metadata.pop("detected_at", utc_now()))

        def apply(state: dict[str, Any]) -> dict[str, Any]:
            previous_empty = state.get("last_known_empty_webhook_check")
            incident = {
                "incident_id": str(uuid.uuid4()),
                "kind": "unauthorized_webhook",
                "status": "detected",
                "last_known_empty_before_incident": previous_empty,
                "detected_at": detected_at,
                "removed_at": None,
                "first_recovered_update": None,
                **metadata,
            }
            incidents = state.setdefault("incidents", [])
            if not isinstance(incidents, list):
                incidents = state["incidents"] = []
            incidents.append(incident)
            del incidents[:-self.MAX_INCIDENTS]
            state["current_incident_id"] = incident["incident_id"]
            state.update(
                webhook_detected_at=detected_at,
                webhook_removed_at=None,
                first_recovered_update_after_incident=None,
                last_known_empty_before_incident=previous_empty,
                **metadata,
            )
            cutoff = _parse_utc(detected_at)
            recent = 0
            if cutoff is not None:
                for item in incidents:
                    timestamp = _parse_utc(item.get("detected_at") if isinstance(item, dict) else None)
                    if timestamp is not None and cutoff - timestamp <= timedelta(minutes=10):
                        recent += 1
            return {**incident, "detections_in_10_minutes": recent}

        return self.mutate(apply)

    def mark_webhook_removed(self, incident_id: str, *, removed_at: str | None = None) -> None:
        removed = removed_at or utc_now()

        def apply(state: dict[str, Any]) -> None:
            for incident in reversed(state.get("incidents", [])):
                if isinstance(incident, dict) and incident.get("incident_id") == incident_id:
                    incident["removed_at"] = removed
                    incident["status"] = "auto_recovered"
                    break
            state["webhook_removed_at"] = removed

        self.mutate(apply)

    def mark_webhook_recovery_failed(self, incident_id: str, *, failed_at: str | None = None) -> None:
        failed = failed_at or utc_now()

        def apply(state: dict[str, Any]) -> None:
            for incident in reversed(state.get("incidents", [])):
                if isinstance(incident, dict) and incident.get("incident_id") == incident_id:
                    incident["recovery_failed_at"] = failed
                    incident["status"] = "recovery_failed"
                    break

        self.mutate(apply)


    def should_send_alert(
        self,
        key: str,
        *,
        severity_rank: int,
        sent_at: str | None = None,
        cooldown_seconds: int = 600,
    ) -> bool:
        now_value = sent_at or utc_now()
        now = _parse_utc(now_value) or datetime.now(UTC)

        def apply(state: dict[str, Any]) -> bool:
            alerts = state.setdefault("alert_last_sent", {})
            if not isinstance(alerts, dict):
                alerts = state["alert_last_sent"] = {}
            previous = alerts.get(key)
            if isinstance(previous, dict):
                previous_time = _parse_utc(previous.get("sent_at"))
                previous_rank = previous.get("severity_rank")
                if (
                    previous_time is not None
                    and isinstance(previous_rank, int)
                    and now - previous_time < timedelta(seconds=cooldown_seconds)
                    and severity_rank <= previous_rank
                ):
                    return False
            alerts[key] = {"sent_at": now_value, "severity_rank": severity_rank}
            return True

        return bool(self.mutate(apply))

    def record_received_update(self, update_id: int, *, received_at: str) -> None:
        def apply(state: dict[str, Any]) -> None:
            previous_received = state.get("max_received_update_id")
            if not isinstance(previous_received, int) or update_id > previous_received:
                state["max_received_update_id"] = update_id
                state["max_received_update_timestamp"] = received_at

            current_id = state.get("current_incident_id")
            for incident in reversed(state.get("incidents", [])):
                if not isinstance(incident, dict) or incident.get("incident_id") != current_id:
                    continue
                if incident.get("removed_at") and not incident.get("first_recovered_update"):
                    recovered = {"update_id": update_id, "received_at": received_at}
                    incident["first_recovered_update"] = recovered
                    state["first_recovered_update_after_incident"] = recovered
                break

        self.mutate(apply)

    def record_completed_update(
        self,
        update_id: int,
        *,
        completed_at: str,
        handled: bool,
        success: bool,
    ) -> None:
        def apply(state: dict[str, Any]) -> None:
            previous_completed = state.get("max_completed_update_id")
            if not isinstance(previous_completed, int) or update_id > previous_completed:
                state["max_completed_update_id"] = update_id
                state["max_completed_update_timestamp"] = completed_at
                state["max_completed_update_handled"] = handled
                state["max_completed_update_success"] = success
                state["last_processed_update_id"] = update_id
                state["last_processed_update_timestamp"] = completed_at

        self.mutate(apply)

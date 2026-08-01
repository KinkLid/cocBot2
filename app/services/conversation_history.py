from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

_USER_FILE_RE = re.compile(r"^user_(\d+)\.jsonl(?:\.(\d+))?$")


@dataclass(frozen=True, slots=True)
class ConversationUser:
    telegram_id: int
    display_name: str
    username: str | None
    last_recorded_at: str | None


@dataclass(frozen=True, slots=True)
class ConversationPage:
    user: ConversationUser
    records: list[dict[str, Any]]
    page: int
    total_pages: int
    total_records: int


class ConversationHistoryService:
    """Read-only view over per-user JSONL conversation logs."""

    def __init__(self, directory: str | Path, *, page_size: int = 6) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.directory = Path(directory)
        self.page_size = page_size

    def _user_ids(self) -> list[int]:
        if not self.directory.exists():
            return []
        result: set[int] = set()
        for path in self.directory.iterdir():
            match = _USER_FILE_RE.match(path.name)
            if match and path.is_file():
                result.add(int(match.group(1)))
        return sorted(result)

    def _paths_for(self, telegram_id: int) -> list[Path]:
        if telegram_id <= 0 or not self.directory.exists():
            return []
        base_name = f"user_{telegram_id}.jsonl"
        rotated: list[tuple[int, Path]] = []
        current: Path | None = None
        for path in self.directory.glob(f"{base_name}*"):
            match = _USER_FILE_RE.match(path.name)
            if not match or int(match.group(1)) != telegram_id or not path.is_file():
                continue
            suffix = match.group(2)
            if suffix is None:
                current = path
            else:
                rotated.append((int(suffix), path))
        paths = [path for _index, path in sorted(rotated, reverse=True)]
        if current is not None:
            paths.append(current)
        return paths

    @staticmethod
    def _read_path(path: Path) -> Iterator[dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        yield value
        except (FileNotFoundError, OSError, UnicodeError):
            return

    def _records(self, telegram_id: int) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self._paths_for(telegram_id):
            records.extend(self._read_path(path))
        return records

    @staticmethod
    def _identity(telegram_id: int, records: list[dict[str, Any]]) -> ConversationUser:
        username: str | None = None
        first_name: str | None = None
        last_name: str | None = None
        last_recorded_at: str | None = None

        for record in reversed(records):
            if last_recorded_at is None and isinstance(record.get("recorded_at"), str):
                last_recorded_at = record["recorded_at"]
            if username is None:
                value = record.get("username") or record.get("chat_username")
                if isinstance(value, str) and value.strip():
                    username = value.strip()
            if first_name is None:
                value = record.get("first_name") or record.get("chat_first_name")
                if isinstance(value, str) and value.strip():
                    first_name = value.strip()
            if last_name is None:
                value = record.get("last_name") or record.get("chat_last_name")
                if isinstance(value, str) and value.strip():
                    last_name = value.strip()
            if username is not None and first_name is not None and last_recorded_at is not None:
                break

        name_parts = [part for part in (first_name, last_name) if part]
        display_name = " ".join(name_parts) or (f"@{username}" if username else f"Пользователь {telegram_id}")
        return ConversationUser(
            telegram_id=telegram_id,
            display_name=display_name,
            username=username,
            last_recorded_at=last_recorded_at,
        )

    def list_users(self) -> list[ConversationUser]:
        users: list[ConversationUser] = []
        for telegram_id in self._user_ids():
            records = self._records(telegram_id)
            if records:
                users.append(self._identity(telegram_id, records))
        users.sort(key=lambda item: item.last_recorded_at or "", reverse=True)
        return users

    def get_page(self, telegram_id: int, page: int = 0) -> ConversationPage | None:
        records = self._records(telegram_id)
        if not records:
            return None
        total_records = len(records)
        total_pages = max(1, (total_records + self.page_size - 1) // self.page_size)
        page = min(max(page, 0), total_pages - 1)
        end = total_records - page * self.page_size
        start = max(0, end - self.page_size)
        return ConversationPage(
            user=self._identity(telegram_id, records),
            records=records[start:end],
            page=page,
            total_pages=total_pages,
            total_records=total_records,
        )

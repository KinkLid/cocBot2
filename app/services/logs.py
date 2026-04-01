from __future__ import annotations

from pathlib import Path


class LogService:
    def __init__(self, log_file: str) -> None:
        self.log_file = Path(log_file)

    def tail(self, lines: int = 200) -> str:
        if not self.log_file.exists():
            return "Лог-файл пока не создан."
        content = self.log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(content[-lines:])

    def file_path(self) -> Path:
        return self.log_file

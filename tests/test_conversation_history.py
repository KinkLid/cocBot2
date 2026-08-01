from __future__ import annotations

import json
from pathlib import Path

from app.services.conversation_history import ConversationHistoryService


def _write(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def test_conversation_history_lists_users_and_reads_latest_page(tmp_path: Path):
    _write(
        tmp_path / "user_10.jsonl",
        [
            {"recorded_at": "2026-08-01T10:00:00+00:00", "direction": "incoming", "first_name": "Иван", "username": "ivan", "text": "one"},
            {"recorded_at": "2026-08-01T10:01:00+00:00", "direction": "outgoing", "text": "two"},
            {"recorded_at": "2026-08-01T10:02:00+00:00", "direction": "incoming", "first_name": "Иван", "username": "ivan", "text": "three"},
        ],
    )
    service = ConversationHistoryService(tmp_path, page_size=2)

    users = service.list_users()
    assert [(user.telegram_id, user.display_name, user.username) for user in users] == [(10, "Иван", "ivan")]

    latest = service.get_page(10, 0)
    assert latest is not None
    assert [record["text"] for record in latest.records] == ["two", "three"]
    assert latest.total_pages == 2

    older = service.get_page(10, 1)
    assert older is not None
    assert [record["text"] for record in older.records] == ["one"]


def test_conversation_history_reads_rotated_files_oldest_first_and_skips_bad_json(tmp_path: Path):
    _write(tmp_path / "user_20.jsonl.2", [{"recorded_at": "1", "text": "oldest"}])
    (tmp_path / "user_20.jsonl.1").write_text("not json\n" + json.dumps({"recorded_at": "2", "text": "middle"}) + "\n", encoding="utf-8")
    _write(tmp_path / "user_20.jsonl", [{"recorded_at": "3", "text": "newest"}])

    page = ConversationHistoryService(tmp_path, page_size=10).get_page(20)

    assert page is not None
    assert [record["text"] for record in page.records] == ["oldest", "middle", "newest"]


def test_conversation_history_ignores_group_logs_and_missing_users(tmp_path: Path):
    _write(tmp_path / "chat_100.jsonl", [{"recorded_at": "1", "text": "group"}])
    service = ConversationHistoryService(tmp_path)

    assert service.list_users() == []
    assert service.get_page(999) is None

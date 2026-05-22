from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from app.bot.handlers.admin import (
    admin_clan_stats,
    admin_players_sort,
    capital_raid_report_start,
    current_cycle_violations,
    violation_player_selected,
    dev_contribution,
    download_log_file,
    last_logs,
    update_chat_link_finish,
    update_chat_link_start,
)
from app.bot.handlers.common import clan_chat_link
from app.bot.keyboards.main import main_menu
from app.bot.states.chat_link import ChatLinkStates
from app.services.clan_chat import ClanChatService
from app.services.export import ExportService
from app.services.period import PeriodService
from app.services.stats import FormattedStats, StatsService
from tests.fakes import FakeCallback, FakeMessage, FakeState
from app.bot.states.violations import ViolationStates
from tests.test_stats import seed_stats_data


@pytest.mark.asyncio
async def test_json_export_for_current_cycle(session, app_yaml_config, tmp_path: Path):
    await seed_stats_data(session)
    service = ExportService(session, app_yaml_config)
    payload = await service.export_to_dict(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC))
    assert payload["clan"]["tag"] == "#CLAN"
    assert payload["players"][0]["participation"]
    cwl_attacks = [
        attack
        for player in payload["players"]
        for war in player["participation"]
        if war["war_type"] == "cwl"
        for attack in war["attacks"]
    ]
    assert cwl_attacks
    assert cwl_attacks[0]["attacker_position"] == 2
    assert cwl_attacks[0]["defender_position"] == 2


@pytest.mark.asyncio
async def test_json_export_for_previous_cycle(session, app_yaml_config):
    await seed_stats_data(session)
    service = ExportService(session, app_yaml_config)
    payload = await service.export_to_dict(datetime(2026, 3, 6, 0, tzinfo=UTC), datetime(2026, 4, 4, 0, tzinfo=UTC))
    assert payload["period"]["start"].startswith("2026-03-06")


@pytest.mark.asyncio
async def test_json_export_for_custom_period(session, app_yaml_config, tmp_path: Path):
    await seed_stats_data(session)
    service = ExportService(session, app_yaml_config)
    path = await service.export_to_file(datetime(2026, 4, 1, 0, tzinfo=UTC), datetime(2026, 4, 2, 23, tzinfo=UTC), tmp_path / "export.json")
    assert path.exists()
    assert '"players"' in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_clan_chat_link_is_returned_to_user(session, app_context):
    message = FakeMessage(text="🔗 Ссылка на чат клана")
    await clan_chat_link(message, app_context)
    message.answer.assert_awaited()
    assert "https://t.me/test_clan_chat" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_admin_can_update_chat_link(session, app_context):
    state = FakeState()
    message_start = FakeMessage(text="✏️ Обновить ссылку на чат", user_id=1)
    await update_chat_link_start(message_start, state, app_context)
    assert state.state == str(ChatLinkStates.waiting_for_chat_link)

    message_finish = FakeMessage(text="https://t.me/new_link", user_id=1)
    await update_chat_link_finish(message_finish, state, app_context)
    assert state.state is None
    async with app_context.session_maker() as session2:
        url = await ClanChatService(session2, app_context.config).get_chat_url()
    assert url == "https://t.me/new_link"


@pytest.mark.asyncio
async def test_last_200_log_lines_are_returned(app_context):
    log_path = app_context.log_service.file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(f"line {i}" for i in range(250)), encoding="utf-8")
    message = FakeMessage(text="📜 Последние логи", user_id=1)
    await last_logs(message, app_context)
    output = "".join(call.args[0] for call in message.answer.await_args_list)
    assert "line 249" in output
    assert "line 40" not in output


@pytest.mark.asyncio
async def test_full_log_file_can_be_downloaded(app_context):
    log_path = app_context.log_service.file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("hello", encoding="utf-8")
    message = FakeMessage(text="🗂 Скачать лог-файл", user_id=1)
    await download_log_file(message, app_context)
    message.answer_document.assert_awaited()


@pytest.mark.asyncio
async def test_dev_contribution_button_is_admin_only(app_context):
    message = FakeMessage(text="🧪 Dev-вклад", user_id=999)
    await dev_contribution(message, app_context)
    assert "Недостаточно прав" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_admin_clan_stats_split_for_big_report(app_context, monkeypatch):
    long_text = ("Игрок\n" * 1500)

    async def fake_current_cycle(self):
        return SimpleNamespace(start=datetime(2026, 4, 1, 0, tzinfo=UTC), end=datetime(2026, 4, 2, 0, tzinfo=UTC))

    async def fake_clan_stats(self, period_start, period_end, sort_by="clan_order"):
        return FormattedStats(text=long_text, rows=[])

    monkeypatch.setattr(PeriodService, "current_cycle", fake_current_cycle)
    monkeypatch.setattr(StatsService, "clan_stats", fake_clan_stats)

    message = FakeMessage(text="📈 Статистика клана", user_id=1)
    await admin_clan_stats(message, app_context)

    assert message.answer.await_count > 1
    delivered = "".join(call.args[0] for call in message.answer.await_args_list)
    assert delivered == long_text


@pytest.mark.asyncio
async def test_admin_players_list_callback_sends_chunks_when_report_too_long(app_context, monkeypatch):
    long_text = "A" * 5000

    async def fake_current_cycle(self):
        return SimpleNamespace(start=datetime(2026, 4, 1, 0, tzinfo=UTC), end=datetime(2026, 4, 2, 0, tzinfo=UTC))

    async def fake_clan_stats(self, period_start, period_end, sort_by="clan_order"):
        return FormattedStats(text=long_text, rows=[])

    monkeypatch.setattr(PeriodService, "current_cycle", fake_current_cycle)
    monkeypatch.setattr(StatsService, "clan_stats", fake_clan_stats)

    callback = FakeCallback(data="admin_sort:stars", user_id=1)
    await admin_players_sort(callback, app_context)

    callback.message.edit_text.assert_awaited()
    notice = callback.message.edit_text.await_args.args[0]
    assert "Отчет слишком большой" in notice
    assert callback.message.answer.await_count > 1
    delivered = "".join(call.args[0] for call in callback.message.answer.await_args_list)
    assert delivered == long_text


@pytest.mark.asyncio
async def test_capital_button_handler_returns_report_for_admin(app_context, monkeypatch):
    from tests.fakes import FakeState

    message = FakeMessage(text="🏰 Столица", user_id=1)
    await capital_raid_report_start(message, FakeState(), app_context)
    assert "Введите, за сколько последних рейдов" in message.answer.await_args_list[0].args[0]


@pytest.mark.asyncio
async def test_capital_button_handler_denies_non_admin(app_context):
    from tests.fakes import FakeState

    message = FakeMessage(text="🏰 Столица", user_id=999)
    await capital_raid_report_start(message, FakeState(), app_context)
    assert "⛔ Недостаточно прав" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_message_too_long_error_no_longer_reproduced_in_admin_callback(app_context, monkeypatch):
    long_text = "B" * 5000

    async def fake_current_cycle(self):
        return SimpleNamespace(start=datetime(2026, 4, 1, 0, tzinfo=UTC), end=datetime(2026, 4, 2, 0, tzinfo=UTC))

    async def fake_clan_stats(self, period_start, period_end, sort_by="clan_order"):
        return FormattedStats(text=long_text, rows=[])

    monkeypatch.setattr(PeriodService, "current_cycle", fake_current_cycle)
    monkeypatch.setattr(StatsService, "clan_stats", fake_clan_stats)

    callback = FakeCallback(data="admin_sort:place", user_id=1)

    async def guarded_edit(text: str, **kwargs):
        if len(text) > 4096:
            raise RuntimeError("MESSAGE_TOO_LONG")
        return None

    callback.message.edit_text = AsyncMock(side_effect=guarded_edit)

    await admin_players_sort(callback, app_context)

    assert callback.message.answer.await_count > 1
    callback.answer.assert_awaited()


@pytest.mark.asyncio
async def test_current_cycle_violations_is_admin_only(app_context):
    message = FakeMessage(text="🚨 Нарушения", user_id=999)
    await current_cycle_violations(message, FakeState(), app_context)
    assert "Недостаточно прав" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_current_cycle_violations_handler_always_replies(app_context, monkeypatch):
    async def fake_current_cycle(self):
        return SimpleNamespace(start=datetime(2026, 4, 1, 0, tzinfo=UTC), end=datetime(2026, 4, 2, 0, tzinfo=UTC))

    async def fake_ranking(self, period_start, period_end):
        return "✅ За текущий цикл нарушений пока нет."

    monkeypatch.setattr(PeriodService, "current_cycle", fake_current_cycle)
    monkeypatch.setattr(StatsService, "violations_ranking_current_cycle", fake_ranking)

    message = FakeMessage(text="🚨 Нарушения", user_id=1)
    await current_cycle_violations(message, FakeState(), app_context)
    message.answer.assert_awaited()


@pytest.mark.asyncio
async def test_current_cycle_violations_sets_state_when_ranked(app_context, monkeypatch):
    async def fake_current_cycle(self):
        return SimpleNamespace(start=datetime(2026, 4, 1, 0, tzinfo=UTC), end=datetime(2026, 4, 2, 0, tzinfo=UTC))

    async def fake_data(self, period_start, period_end):
        return [{"player_tag": "#P1", "player_name": "Lester", "violations": 2}]

    async def fake_text(self, period_start, period_end):
        return "🚨 Нарушения за текущий цикл\n\n1. Lester — 2"

    monkeypatch.setattr(PeriodService, "current_cycle", fake_current_cycle)
    monkeypatch.setattr(StatsService, "violations_ranking_current_cycle_data", fake_data)
    monkeypatch.setattr(StatsService, "violations_ranking_current_cycle", fake_text)

    message = FakeMessage(text="🚨 Нарушения", user_id=1)
    state = FakeState()
    await current_cycle_violations(message, state, app_context)
    assert state.state == str(ViolationStates.awaiting_violation_player_number)
    assert (await state.get_data())["violation_player_options"][0]["player_tag"] == "#P1"


@pytest.mark.asyncio
async def test_violation_player_selected_validation_and_back(app_context):
    state = FakeState()
    await state.set_state(ViolationStates.awaiting_violation_player_number)
    await state.update_data(violation_player_options=[{"player_tag": "#P1", "player_name": "Lester", "violations": 2}])

    bad = FakeMessage(text="abc", user_id=1)
    await violation_player_selected(bad, state, app_context)
    assert "Введите номер" in bad.answer.await_args.args[0]
    assert state.state == str(ViolationStates.awaiting_violation_player_number)

    out = FakeMessage(text="9", user_id=1)
    await violation_player_selected(out, state, app_context)
    assert "Нет игрока" in out.answer.await_args.args[0]

    back = FakeMessage(text="⬅️ Назад", user_id=1)
    await violation_player_selected(back, state, app_context)
    assert state.state is None
    assert "Главное меню" in back.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_violation_player_selected_success(app_context, monkeypatch):
    async def fake_current_cycle(self):
        return SimpleNamespace(start=datetime(2026, 4, 1, 0, tzinfo=UTC), end=datetime(2026, 4, 2, 0, tzinfo=UTC))

    async def fake_report(self, period_start, period_end, player_tag, player_name):
        return "🚨 Нарушения игрока: Lester\n\n1. 2026-05-14 08:18 | КВ | 10 -> 8\nКод: above_self\nПричина: test"

    monkeypatch.setattr(PeriodService, "current_cycle", fake_current_cycle)
    monkeypatch.setattr(StatsService, "build_player_violations_report", fake_report)

    state = FakeState()
    await state.set_state(ViolationStates.awaiting_violation_player_number)
    await state.update_data(violation_player_options=[{"player_tag": "#P1", "player_name": "Lester", "violations": 2}])

    message = FakeMessage(text="1", user_id=1)
    await violation_player_selected(message, state, app_context)
    assert state.state is None
    assert "Нарушения игрока" in message.answer.await_args_list[0].args[0]


def test_dev_capital_button_visible_only_for_admin():
    admin = main_menu(True, True)
    user = main_menu(False, True)
    admin_texts = [b.text for row in admin.keyboard for b in row]
    user_texts = [b.text for row in user.keyboard for b in row]
    assert "🧪 Dev-столица" in admin_texts
    assert "🧪 Dev-столица" not in user_texts

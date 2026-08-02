from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.bot.keyboards.admin_panel import admin_panel_keyboard, period_keyboard
from app.bot.keyboards.main import main_menu
from app.models import PlayerAccount
from app.repositories.manual_contribution import ManualContributionRepository
from app.services.period import PeriodService


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_prioritizes_admin_panel():
    markup = main_menu(is_admin=True, is_registered=True)
    texts = [button.text for row in markup.keyboard for button in row]
    assert "🛡 Админка" in texts
    assert texts.index("🛡 Админка") < texts.index("🔗 Привязать игрока")


def test_admin_panel_contains_grouped_sections():
    texts = _button_texts(admin_panel_keyboard())
    assert "⚔️ Война" in texts
    assert "👥 Игроки" in texts
    assert "🚨 Нарушения" in texts
    assert "🏆 Вклад" in texts
    assert "⚙️ Система" in texts
    assert "🔐 Безопасность" in texts


def test_period_keyboard_has_all_supported_modes():
    texts = _button_texts(period_keyboard("contribution"))
    assert texts[:5] == [
        "📆 Текущий цикл",
        "📚 Прошлый цикл",
        "🗂 Выбрать конкретный цикл",
        "♾ За всё время",
        "🗓 Указать даты",
    ]


@pytest.mark.asyncio
async def test_manual_adjustment_repository_accepts_negative_points(session):
    now = datetime(2026, 8, 2, tzinfo=UTC)
    player = PlayerAccount(
        player_tag="#NEG",
        name="Negative",
        town_hall=15,
        current_in_clan=True,
        current_clan_tag="#TEST",
        created_at=now,
        updated_at=now,
    )
    session.add(player)
    await session.flush()

    adjustment = await ManualContributionRepository(session).add_manual_adjustment(
        player_id=player.id,
        clan_tag="#TEST",
        points=-25,
        comment="Корректировка ошибочного начисления",
        created_by_telegram_id=1,
        created_by_username="admin",
        created_at=now,
        operation_token="negative-test-token",
    )
    await session.commit()

    assert adjustment.points == -25


@pytest.mark.asyncio
async def test_period_service_all_time_starts_at_epoch(session):
    period = PeriodService(session).all_time(datetime(2026, 8, 2, tzinfo=UTC))
    assert period.start == datetime(1970, 1, 1, tzinfo=UTC)
    assert period.label == "За всё время"

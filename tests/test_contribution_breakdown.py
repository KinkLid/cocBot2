from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.handlers.admin import (
    contribution_breakdown_selected,
    contribution_breakdown_start,
    my_contribution_breakdown,
)
from app.models.enums import ViolationCode, WarType
from app.services.auth import AuthService
from app.services.contribution_breakdown import ContributionBreakdownService
from app.services.dev_contribution import (
    ContributionCalculation,
    ContributionRankingRow,
    ContributionScoreComponent,
    DevContributionService,
)
from app.services.period import PeriodService
from app.services.registration import RegistrationService
from app.repositories.telegram_user import TelegramUserRepository
from tests.fakes import FakeMessage, FakeState


NOW = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
PERIOD = SimpleNamespace(start=NOW - timedelta(days=7), end=NOW)


def _attack(tag: str, *, position: int, target: int, observed_at: datetime):
    return SimpleNamespace(
        attacker_tag=tag,
        attacker_position=position,
        defender_position=target,
        stars=3,
        destruction=100.0,
        observed_at=observed_at,
    )


def _war(war_id: int, war_type: WarType, end_time: datetime):
    return SimpleNamespace(id=war_id, war_type=war_type, end_time=end_time)


def _calculation(*, donation: int = 37, include_items: bool = True) -> ContributionCalculation:
    regular_war = _war(1, WarType.REGULAR, NOW - timedelta(days=3))
    cwl_war = _war(2, WarType.CWL, NOW - timedelta(days=2))
    components = []
    if include_items:
        components.extend(
            [
                ContributionScoreComponent(
                    kind="attack",
                    player_tag="#P1",
                    score_delta=12.5,
                    attack=_attack("#P1", position=1, target=4, observed_at=NOW - timedelta(days=4)),
                    war=regular_war,
                ),
                ContributionScoreComponent(
                    kind="attack",
                    player_tag="#P1",
                    score_delta=11.8,
                    attack=_attack("#P1", position=1, target=3, observed_at=NOW - timedelta(days=3)),
                    war=cwl_war,
                    violation_code=ViolationCode.ABOVE_SELF,
                ),
                ContributionScoreComponent(
                    kind="unused_attack_penalty",
                    player_tag="#P1",
                    score_delta=-10.0,
                    war=regular_war,
                ),
            ]
        )
    components.append(
        ContributionScoreComponent(
            kind="donations", player_tag="#P1", score_delta=float(donation)
        )
    )
    return ContributionCalculation(
        stats_rows=[SimpleNamespace(player_tag="#P1", player_name="Player", wars=2, player_id=1)],
        components_by_tag={"#P1": components},
        active_violations_by_tag={"#P1": 2},
        donations_by_tag={"#P1": donation},
    )


def _service(monkeypatch, calculation: ContributionCalculation) -> ContributionBreakdownService:
    monkeypatch.setattr(
        DevContributionService,
        "build_contribution_calculation",
        AsyncMock(return_value=calculation),
    )
    return ContributionBreakdownService(object(), SimpleNamespace(main_clan_tag="#CLAN"))


def test_short_breakdown_shows_all_totals(monkeypatch):
    service = _service(monkeypatch, _calculation())
    breakdown = asyncio.run(service.build_player_breakdown("#P1", PERIOD))
    text = service.format_short_breakdown(breakdown)

    assert "Атаки: +24.30" in text
    assert "Неиспользованные атаки: -10.00" in text
    assert "Донаты: +37" in text
    assert "Итого: 51.30" in text


def test_detailed_breakdown_has_regular_cwl_penalty_donation_and_violation(monkeypatch):
    service = _service(monkeypatch, _calculation())
    breakdown = asyncio.run(service.build_player_breakdown("#P1", PERIOD))
    text = service.format_detailed_breakdown(breakdown)

    assert "КВ | 1 -> 4 | 3⭐ 100%" in text
    assert "ЛВК | 1 -> 3 | 3⭐ 100% | Нарушение: above_self" in text
    assert "Штраф за неиспользованную атаку | КВ" in text
    assert "Донаты войск за цикл" in text


def test_breakdown_final_score_matches_dev_contribution_ranking(monkeypatch):
    calculation = _calculation()
    service = _service(monkeypatch, calculation)
    monkeypatch.setattr(DevContributionService, "is_newcomer", AsyncMock(return_value=False))

    breakdown = asyncio.run(service.build_player_breakdown("#P1", PERIOD))
    ranking = asyncio.run(
        DevContributionService(
            object(), SimpleNamespace(main_clan_tag="#CLAN")
        ).build_contribution_ranking(PERIOD)
    )

    assert breakdown.final_score == ranking[0].score


def test_donation_only_and_zero_breakdowns(monkeypatch):
    donation_service = _service(monkeypatch, _calculation(donation=37, include_items=False))
    donation_breakdown = asyncio.run(donation_service.build_player_breakdown("#P1", PERIOD))
    assert donation_breakdown.final_score == 37
    assert donation_breakdown.attack_score_total == 0

    zero_service = _service(monkeypatch, _calculation(donation=0, include_items=False))
    zero_breakdown = asyncio.run(zero_service.build_player_breakdown("#P1", PERIOD))
    assert zero_breakdown.final_score == 0
    assert "Итого: 0.00" in zero_service.format_short_breakdown(zero_breakdown)


class _Context:
    def __init__(self, config):
        self.config = config
        self.auth_service = AuthService(config)
        self.clash_client = object()

    @asynccontextmanager
    async def session_maker(self):
        yield object()


def test_my_contribution_reports_unlinked_user(app_yaml_config, monkeypatch):
    monkeypatch.setattr(TelegramUserRepository, "get_by_telegram_id", AsyncMock(return_value=None))
    message = FakeMessage("📋 Мой вклад", user_id=777)

    asyncio.run(my_contribution_breakdown(message, _Context(app_yaml_config)))

    message.answer.assert_awaited_once_with("⚠️ Вы еще не привязаны к участнику клана.")


def test_admin_breakdown_is_admin_only(app_yaml_config):
    message = FakeMessage("🧾 Разбор вклада", user_id=777)
    state = FakeState()

    asyncio.run(contribution_breakdown_start(message, state, _Context(app_yaml_config)))

    message.answer.assert_awaited_once_with("⛔ Недостаточно прав")
    assert state.state is None


def test_invalid_player_number_keeps_state(app_yaml_config):
    admin_id = app_yaml_config.admin_telegram_ids[0]
    message = FakeMessage("99", user_id=admin_id)
    state = FakeState()
    asyncio.run(
        state.update_data(
            contribution_breakdown_players=[{"player_tag": "#P1", "player_name": "Player"}]
        )
    )
    asyncio.run(contribution_breakdown_selected(message, state, _Context(app_yaml_config)))

    message.answer.assert_awaited_once_with("⚠️ Нет игрока с таким номером.")
    assert state._data["contribution_breakdown_players"]


def test_back_clears_state_and_returns_menu(app_yaml_config, monkeypatch):
    admin_id = app_yaml_config.admin_telegram_ids[0]
    monkeypatch.setattr(RegistrationService, "is_registered", AsyncMock(return_value=True))
    message = FakeMessage("⬅️ Назад", user_id=admin_id)
    state = FakeState()
    asyncio.run(state.update_data(contribution_breakdown_players=[{"player_tag": "#P1"}]))

    asyncio.run(contribution_breakdown_selected(message, state, _Context(app_yaml_config)))

    assert state.state is None
    assert state._data == {}
    assert message.answer.await_args.args[0] == "Главное меню"


def test_admin_start_shows_numbered_ranking_and_sets_state(app_yaml_config, monkeypatch):
    admin_id = app_yaml_config.admin_telegram_ids[0]
    ranking = [ContributionRankingRow("#P1", "Player", 2, 51.3, False, 2, 37)]
    monkeypatch.setattr(DevContributionService, "build_contribution_ranking", AsyncMock(return_value=ranking))
    monkeypatch.setattr(PeriodService, "current_cycle", AsyncMock(return_value=PERIOD))
    message = FakeMessage("🧾 Разбор вклада", user_id=admin_id)
    state = FakeState()

    asyncio.run(contribution_breakdown_start(message, state, _Context(app_yaml_config)))

    sent = message.answer.await_args.args[0]
    assert "1. Player — 51.30" in sent
    assert "Введите номер игрока" in sent
    assert state._data["contribution_breakdown_players"][0]["player_tag"] == "#P1"

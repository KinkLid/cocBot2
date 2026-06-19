from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.handlers.admin import (
    contribution_breakdown_selected,
    contribution_breakdown_start,
    my_contribution_breakdown,
    my_contribution_breakdown_selected,
)
from app.bot.states.contribution_breakdown import ContributionBreakdownStates
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
from app.repositories.player_account import PlayerAccountRepository
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


def _calculation(*, donation: int = 380, include_items: bool = True) -> ContributionCalculation:
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
            kind="donations",
            player_tag="#P1",
            score_delta=round(donation * 0.01, 2),
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
    assert "Донаты: +3.80 (сырой донат: 380)" in text
    assert "Итого: 18.10" in text


def test_detailed_breakdown_has_regular_cwl_penalty_donation_and_violation(monkeypatch):
    service = _service(monkeypatch, _calculation())
    breakdown = asyncio.run(service.build_player_breakdown("#P1", PERIOD))
    text = service.format_detailed_breakdown(breakdown)

    assert "КВ | 1 -> 4 | 3⭐ 100%" in text
    assert "ЛВК | 1 -> 3 | 3⭐ 100% | Нарушение: above_self" in text
    assert "Штраф за неиспользованную атаку | КВ" in text
    assert "Донаты войск за цикл | Сырой донат: 380" in text
    assert "+3.80" in text
    donation_item = next(item for item in breakdown.items if item.kind == "donations")
    assert donation_item.title == "Донаты войск за цикл"
    assert donation_item.score_delta == 3.8
    assert donation_item.details == "Сырой донат: 380"


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


def test_breakdown_does_not_show_too_low_without_component_violation(monkeypatch):
    regular_war = _war(3, WarType.REGULAR, NOW - timedelta(days=1))
    calculation = ContributionCalculation(
        stats_rows=[
            SimpleNamespace(
                player_tag="#DARK",
                player_name="THE_DARK_KING",
                wars=1,
                player_id=1,
            )
        ],
        components_by_tag={
            "#DARK": [
                ContributionScoreComponent(
                    kind="attack",
                    player_tag="#DARK",
                    score_delta=48.0,
                    attack=_attack(
                        "#DARK",
                        position=3,
                        target=15,
                        observed_at=NOW - timedelta(hours=1),
                    ),
                    war=regular_war,
                    violation_code=None,
                )
            ]
        },
        active_violations_by_tag={"#DARK": 0},
        donations_by_tag={"#DARK": 0},
    )
    service = _service(monkeypatch, calculation)

    breakdown = asyncio.run(service.build_player_breakdown("#DARK", PERIOD))
    text = service.format_detailed_breakdown(breakdown)

    assert "КВ | 3 -> 15 | 3⭐ 100%" in text
    assert "Нарушение: too_low" not in text
    assert breakdown.attack_score_total == 48.0
    assert breakdown.final_score == 48.0


def test_breakdown_shows_saved_too_low_component_violation(monkeypatch):
    regular_war = _war(4, WarType.REGULAR, NOW - timedelta(days=1))
    calculation = ContributionCalculation(
        stats_rows=[
            SimpleNamespace(
                player_tag="#DARK",
                player_name="THE_DARK_KING",
                wars=1,
                player_id=1,
            )
        ],
        components_by_tag={
            "#DARK": [
                ContributionScoreComponent(
                    kind="attack",
                    player_tag="#DARK",
                    score_delta=-36.0,
                    attack=_attack(
                        "#DARK",
                        position=3,
                        target=18,
                        observed_at=NOW - timedelta(hours=1),
                    ),
                    war=regular_war,
                    violation_code=ViolationCode.TOO_LOW,
                )
            ]
        },
        active_violations_by_tag={"#DARK": 1},
        donations_by_tag={"#DARK": 0},
    )
    service = _service(monkeypatch, calculation)

    breakdown = asyncio.run(service.build_player_breakdown("#DARK", PERIOD))
    text = service.format_detailed_breakdown(breakdown)

    assert "КВ | 3 -> 18 | 3⭐ 100% | Нарушение: too_low" in text
    assert breakdown.attack_score_total == -36.0
    assert breakdown.final_score == -36.0


@pytest.mark.parametrize(
    ("raw_donations", "donation_points"),
    [(0, 0.0), (1, 0.01), (10, 0.1), (100, 1.0), (380, 3.8), (1000, 10.0)],
)
def test_donation_only_breakdown_uses_weighted_points(
    monkeypatch, raw_donations, donation_points
):
    service = _service(
        monkeypatch, _calculation(donation=raw_donations, include_items=False)
    )
    breakdown = asyncio.run(service.build_player_breakdown("#P1", PERIOD))

    assert breakdown.final_score == donation_points
    assert breakdown.donation_total == raw_donations
    assert breakdown.donation_score_total == donation_points
    assert breakdown.attack_score_total == 0
    assert (
        f"Донаты: +{donation_points:.2f} (сырой донат: {raw_donations})"
        in service.format_short_breakdown(breakdown)
    )


class _Context:
    def __init__(self, config):
        self.config = config
        self.auth_service = AuthService(config)
        self.clash_client = object()

    @asynccontextmanager
    async def session_maker(self):
        yield object()


def test_my_contribution_reports_unlinked_user(app_yaml_config, monkeypatch):
    monkeypatch.setattr(
        TelegramUserRepository,
        "get_by_telegram_id",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(TelegramUserRepository, "get_links", AsyncMock(return_value=[]))
    message = FakeMessage("📋 Мой вклад", user_id=777)
    state = FakeState()

    asyncio.run(my_contribution_breakdown(message, state, _Context(app_yaml_config)))

    message.answer.assert_awaited_once_with("⚠️ Вы еще не привязаны к участнику клана.")
    assert state.state is None


def test_my_contribution_single_account_shows_breakdown_without_state(
    app_yaml_config, monkeypatch
):
    link = SimpleNamespace(player_tag="#P1")
    monkeypatch.setattr(
        TelegramUserRepository,
        "get_by_telegram_id",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(TelegramUserRepository, "get_links", AsyncMock(return_value=[link]))
    monkeypatch.setattr(PeriodService, "current_cycle", AsyncMock(return_value=PERIOD))
    build_breakdown = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(
        ContributionBreakdownService, "build_player_breakdown", build_breakdown
    )
    monkeypatch.setattr(
        ContributionBreakdownService,
        "format_short_breakdown",
        lambda self, breakdown: "short report",
    )
    message = FakeMessage("📋 Мой вклад", user_id=777)
    state = FakeState()

    asyncio.run(my_contribution_breakdown(message, state, _Context(app_yaml_config)))

    build_breakdown.assert_awaited_once_with("#P1", PERIOD)
    message.answer.assert_awaited_once_with("short report")
    assert state.state is None
    assert state._data == {}


def test_my_contribution_multiple_accounts_shows_options_and_sets_state(
    app_yaml_config, monkeypatch
):
    links = [SimpleNamespace(player_tag="#P1"), SimpleNamespace(player_tag="#P2")]
    players = {
        "#P1": SimpleNamespace(name="Nickname1"),
        "#P2": SimpleNamespace(name="Nickname2"),
    }
    monkeypatch.setattr(
        TelegramUserRepository,
        "get_by_telegram_id",
        AsyncMock(return_value=SimpleNamespace(id=1)),
    )
    monkeypatch.setattr(TelegramUserRepository, "get_links", AsyncMock(return_value=links))
    monkeypatch.setattr(
        PlayerAccountRepository,
        "get_by_tag",
        AsyncMock(side_effect=lambda tag: players[tag]),
    )
    message = FakeMessage("📋 Мой вклад", user_id=777)
    state = FakeState()

    asyncio.run(my_contribution_breakdown(message, state, _Context(app_yaml_config)))

    sent = message.answer.await_args.args[0]
    assert "📋 Мой вклад" in sent
    assert "1. Nickname1 (#P1)" in sent
    assert "2. Nickname2 (#P2)" in sent
    assert "Введите номер аккаунта или нажмите ⬅️ Назад." in sent
    assert state.state == str(
        ContributionBreakdownStates.awaiting_my_contribution_player_number
    )
    assert state._data["my_contribution_options"] == [
        {"player_tag": "#P1", "player_name": "Nickname1"},
        {"player_tag": "#P2", "player_name": "Nickname2"},
    ]


def _my_contribution_selection_state() -> FakeState:
    state = FakeState()
    asyncio.run(
        state.update_data(
            my_contribution_options=[
                {"player_tag": "#P1", "player_name": "Nickname1"},
                {"player_tag": "#P2", "player_name": "Nickname2"},
            ]
        )
    )
    asyncio.run(
        state.set_state(
            ContributionBreakdownStates.awaiting_my_contribution_player_number
        )
    )
    return state


def test_my_contribution_valid_number_shows_selected_breakdown_and_clears_state(
    app_yaml_config, monkeypatch
):
    monkeypatch.setattr(PeriodService, "current_cycle", AsyncMock(return_value=PERIOD))
    build_breakdown = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(
        ContributionBreakdownService, "build_player_breakdown", build_breakdown
    )
    monkeypatch.setattr(
        ContributionBreakdownService,
        "format_short_breakdown",
        lambda self, breakdown: "selected short report",
    )
    message = FakeMessage("2", user_id=777)
    state = _my_contribution_selection_state()

    asyncio.run(
        my_contribution_breakdown_selected(message, state, _Context(app_yaml_config))
    )

    build_breakdown.assert_awaited_once_with("#P2", PERIOD)
    message.answer.assert_awaited_once_with("selected short report")
    assert state.state is None
    assert state._data == {}


def test_my_contribution_selected_account_error_clears_state(
    app_yaml_config, monkeypatch
):
    monkeypatch.setattr(PeriodService, "current_cycle", AsyncMock(return_value=PERIOD))
    monkeypatch.setattr(
        ContributionBreakdownService,
        "build_player_breakdown",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    message = FakeMessage("1", user_id=777)
    state = _my_contribution_selection_state()

    asyncio.run(
        my_contribution_breakdown_selected(message, state, _Context(app_yaml_config))
    )

    message.answer.assert_awaited_once_with(
        "⚠️ Не удалось загрузить вклад по выбранному аккаунту. Попробуйте позже."
    )
    assert state.state is None
    assert state._data == {}


def test_my_contribution_non_numeric_value_keeps_state(app_yaml_config):
    message = FakeMessage("abc", user_id=777)
    state = _my_contribution_selection_state()

    asyncio.run(
        my_contribution_breakdown_selected(message, state, _Context(app_yaml_config))
    )

    message.answer.assert_awaited_once_with(
        "⚠️ Введите номер аккаунта из списка или нажмите ⬅️ Назад."
    )
    assert state.state == str(
        ContributionBreakdownStates.awaiting_my_contribution_player_number
    )
    assert state._data["my_contribution_options"]


def test_my_contribution_out_of_range_number_keeps_state(app_yaml_config):
    message = FakeMessage("3", user_id=777)
    state = _my_contribution_selection_state()

    asyncio.run(
        my_contribution_breakdown_selected(message, state, _Context(app_yaml_config))
    )

    message.answer.assert_awaited_once_with("⚠️ Нет аккаунта с таким номером.")
    assert state.state == str(
        ContributionBreakdownStates.awaiting_my_contribution_player_number
    )
    assert state._data["my_contribution_options"]


def test_my_contribution_back_clears_state_and_returns_menu(
    app_yaml_config, monkeypatch
):
    monkeypatch.setattr(RegistrationService, "is_registered", AsyncMock(return_value=True))
    message = FakeMessage("⬅️ Назад", user_id=777)
    state = _my_contribution_selection_state()

    asyncio.run(
        my_contribution_breakdown_selected(message, state, _Context(app_yaml_config))
    )

    assert state.state is None
    assert state._data == {}
    assert message.answer.await_args.args[0] == "Главное меню"


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

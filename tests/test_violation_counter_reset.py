from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.bot.handlers.admin import (
    reset_violation_counter_amount_selected,
    reset_violation_counter_selected,
    reset_violation_counter_start,
)
from app.bot.states.violations import ViolationStates
from app.models import Attack, CapitalRaidViolation, CapitalRaidWeekend, PlayerAccount, Violation, ViolationCounterReset, War
from app.models.enums import ViolationCode, WarType
from app.repositories.violation_counter_reset import ViolationCounterResetRepository
from app.services.active_violation_counter import ActiveViolationCounterService
from app.services.dev_contribution import ContributionRankingRow, DevContributionService
from app.services.period import PeriodService
from app.services.stats import StatsService
from tests.fakes import FakeMessage, FakeState


def _cycle():
    return datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC)


async def _seed_player(session, tag="#P1", name="Alpha", rank=1):
    now = datetime(2026, 5, 10, tzinfo=UTC)
    player = PlayerAccount(player_tag=tag, name=name, town_hall=16, current_clan_tag="#CLAN", current_clan_name="Clan", current_clan_rank=rank, current_in_clan=True, last_seen_in_clan_at=now, created_at=now, updated_at=now)
    session.add(player)
    await session.flush()
    return player


async def _seed_history(session, *, tag="#P1", name="Alpha", rank=1, war_count=4, capital_count=1, start=None):
    start = start or datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    player = await _seed_player(session, tag, name, rank)
    war = War(war_uid=f"war-{tag}", clan_tag="#CLAN", clan_name="Clan", opponent_tag="#E", opponent_name="Enemy", war_type=WarType.REGULAR, state="war_ended", team_size=15, is_friendly=False, start_time=start - timedelta(days=2), end_time=start - timedelta(days=1), preparation_start_time=start - timedelta(days=3), source_payload={})
    session.add(war)
    await session.flush()
    for i in range(war_count):
        attack = Attack(war_id=war.id, attacker_player_id=player.id, attacker_tag=tag, attacker_name=name, attacker_position=10, attacker_town_hall=16, defender_tag=f"#E{i}", defender_name=f"Enemy {i}", defender_position=5, defender_town_hall=16, stars=2, destruction=80, attack_order=i + 1, observed_at=start + timedelta(minutes=i))
        session.add(attack)
        await session.flush()
        session.add(Violation(attack_id=attack.id, war_id=war.id, player_tag=tag, code=ViolationCode.ABOVE_SELF, reason_text=f"history {i}", player_position=10, target_position=5, detected_at=start + timedelta(minutes=i), is_manual=False))
    for j in range(capital_count):
        weekend = CapitalRaidWeekend(clan_tag="#CLAN", raid_season_id=f"weekend-{tag}-{j}", state="ended", start_time=start, end_time=start + timedelta(minutes=10 + j), total_loot=0, total_attacks=0, enemy_districts_destroyed=0, offensive_reward=0, defensive_reward=0, processed_at=start + timedelta(minutes=10 + j))
        session.add(weekend)
        await session.flush()
        session.add(CapitalRaidViolation(weekend_id=weekend.id, player_tag=tag, player_name=name, code="capital_under_5_attacks", reason_text="capital history", attacks=4, detected_at=start + timedelta(minutes=10 + j)))
    await session.commit()
    return player, war


async def _counts(session, tag="#P1"):
    cycle_start, cycle_end = _cycle()
    return await ActiveViolationCounterService(session).count_for_player(tag, cycle_start, cycle_end)


async def _reduce(session, tag, amount, at):
    cycle_start, cycle_end = _cycle()
    return await ActiveViolationCounterService(session).reduce_for_player(player_tag=tag, cycle_start=cycle_start, cycle_end=cycle_end, amount=amount, admin_telegram_id=1, reset_at=at)


@pytest.mark.asyncio
async def test_partial_reset_of_one_decreases_active_counter_without_deleting_history(session, app_yaml_config):
    player, _ = await _seed_history(session)
    assert await _reduce(session, player.player_tag, 1, datetime(2026, 5, 21, tzinfo=UTC)) == 4
    await session.commit()
    assert await _counts(session) == 4
    assert await session.scalar(select(func.count(Violation.id))) == 4
    assert await session.scalar(select(func.count(CapitalRaidViolation.id))) == 1
    resets = (await session.scalars(select(ViolationCounterReset))).all()
    assert [r.reset_amount for r in resets] == [1]


@pytest.mark.asyncio
async def test_partial_reset_of_two_can_remove_contribution_cross(session, app_yaml_config):
    player, _ = await _seed_history(session, war_count=2, capital_count=1)
    assert "❌" in DevContributionService(session, app_yaml_config).format_contribution_ranking([ContributionRankingRow(player.player_tag, player.name, 1, 100, False, await _counts(session))])
    await _reduce(session, player.player_tag, 2, datetime(2026, 5, 21, tzinfo=UTC)); await session.commit()
    assert await _counts(session) == 1
    assert "❌" not in DevContributionService(session, app_yaml_config).format_contribution_ranking([ContributionRankingRow(player.player_tag, player.name, 1, 100, False, 1)])


@pytest.mark.asyncio
async def test_multiple_partial_resets_are_cumulative(session):
    player, _ = await _seed_history(session, war_count=4, capital_count=0)
    await _reduce(session, player.player_tag, 1, datetime(2026, 5, 21, tzinfo=UTC))
    await _reduce(session, player.player_tag, 2, datetime(2026, 5, 22, tzinfo=UTC))
    await session.commit()
    assert await _counts(session) == 1
    assert [r.reset_amount for r in (await session.scalars(select(ViolationCounterReset).order_by(ViolationCounterReset.reset_at))).all()] == [1, 2]


@pytest.mark.asyncio
async def test_partial_reset_cannot_exceed_active_counter(session):
    player, _ = await _seed_history(session, war_count=1, capital_count=0)
    with pytest.raises(ValueError):
        await _reduce(session, player.player_tag, 2, datetime(2026, 5, 21, tzinfo=UTC))
    assert await session.scalar(select(func.count(ViolationCounterReset.id))) == 0


@pytest.mark.asyncio
async def test_partial_reset_rejects_amount_outside_one_two_three(session):
    player, _ = await _seed_history(session)
    for amount in (0, 4):
        with pytest.raises(ValueError):
            await _reduce(session, player.player_tag, amount, datetime(2026, 5, 21, tzinfo=UTC))


@pytest.mark.asyncio
async def test_legacy_null_reset_keeps_old_full_reset_semantics(session):
    player, war = await _seed_history(session, war_count=2, capital_count=1)
    cycle_start, _ = _cycle()
    session.add(ViolationCounterReset(player_tag=player.player_tag, cycle_start=cycle_start, reset_at=datetime(2026, 5, 21, tzinfo=UTC), reset_by_admin_telegram_id=1, reset_amount=None))
    attack = Attack(war_id=war.id, attacker_player_id=player.id, attacker_tag=player.player_tag, attacker_name=player.name, attacker_position=10, attacker_town_hall=16, defender_tag="#N", defender_name="N", defender_position=5, defender_town_hall=16, stars=1, destruction=1, attack_order=99, observed_at=datetime(2026, 5, 22, tzinfo=UTC))
    session.add(attack); await session.flush()
    session.add(Violation(attack_id=attack.id, war_id=war.id, player_tag=player.player_tag, code=ViolationCode.ABOVE_SELF, reason_text="new", player_position=10, target_position=5, detected_at=attack.observed_at, is_manual=False))
    await session.commit()
    assert await _counts(session) == 1
    assert await session.scalar(select(func.count(Violation.id))) == 3
    assert await session.scalar(select(func.count(CapitalRaidViolation.id))) == 1


@pytest.mark.asyncio
async def test_partial_resets_before_latest_legacy_reset_are_ignored(session):
    player, war = await _seed_history(session, war_count=1, capital_count=0)
    cycle_start, _ = _cycle()
    await ViolationCounterResetRepository(session).add_reset(player.player_tag, cycle_start, datetime(2026, 5, 20, 12, tzinfo=UTC), 1, 1)
    session.add(ViolationCounterReset(player_tag=player.player_tag, cycle_start=cycle_start, reset_at=datetime(2026, 5, 21, tzinfo=UTC), reset_by_admin_telegram_id=1, reset_amount=None))
    attack = Attack(war_id=war.id, attacker_player_id=player.id, attacker_tag=player.player_tag, attacker_name=player.name, attacker_position=10, attacker_town_hall=16, defender_tag="#N", defender_name="N", defender_position=5, defender_town_hall=16, stars=1, destruction=1, attack_order=2, observed_at=datetime(2026, 5, 22, tzinfo=UTC))
    session.add(attack); await session.flush()
    session.add(Violation(attack_id=attack.id, war_id=war.id, player_tag=player.player_tag, code=ViolationCode.ABOVE_SELF, reason_text="new", player_position=10, target_position=5, detected_at=attack.observed_at, is_manual=False))
    await session.commit()
    assert await _counts(session) == 1


@pytest.mark.asyncio
async def test_history_ranking_keeps_player_after_active_counter_becomes_zero(session, app_yaml_config):
    player, _ = await _seed_history(session, war_count=2, capital_count=0)
    await _reduce(session, player.player_tag, 2, datetime(2026, 5, 21, tzinfo=UTC)); await session.commit()
    cycle_start, cycle_end = _cycle()
    rows = await StatsService(session, app_yaml_config).violations_ranking_current_cycle_data(cycle_start, cycle_end)
    assert rows[0]["player_tag"] == player.player_tag and rows[0]["active_violations"] == 0


@pytest.mark.asyncio
async def test_player_violation_report_keeps_all_entries_after_partial_reset(session, app_yaml_config):
    player, _ = await _seed_history(session, war_count=2, capital_count=1)
    await _reduce(session, player.player_tag, 3, datetime(2026, 5, 21, tzinfo=UTC)); await session.commit()
    text = await StatsService(session, app_yaml_config).build_player_violations_report(*_cycle(), player.player_tag, player.name)
    assert "Активный счетчик нарушений: 0" in text
    assert text.count("Причина:") == 3


@pytest.mark.asyncio
async def test_player_and_clan_stats_use_active_violation_counter(session, app_yaml_config):
    player, _ = await _seed_history(session, war_count=2, capital_count=0)
    await _reduce(session, player.player_tag, 1, datetime(2026, 5, 21, tzinfo=UTC)); await session.commit()
    svc = StatsService(session, app_yaml_config)
    assert (await svc.player_stats(*_cycle(), player.player_tag)).violations == 1
    assert (await svc.clan_stats(*_cycle())).rows[0].violations == 1


@pytest.mark.asyncio
async def test_violation_reset_options_exclude_zero_active_players(session, app_yaml_config):
    player, _ = await _seed_history(session, war_count=1, capital_count=0)
    await _reduce(session, player.player_tag, 1, datetime(2026, 5, 21, tzinfo=UTC)); await session.commit()
    assert await StatsService(session, app_yaml_config).violation_counter_reset_options(*_cycle()) == []


@pytest.mark.asyncio
async def test_reset_player_selection_requests_amount_instead_of_resetting(app_context, monkeypatch):
    async def current_cycle(self): return SimpleNamespace(start=_cycle()[0], end=_cycle()[1])
    monkeypatch.setattr(PeriodService, "current_cycle", current_cycle)
    async def opts(self, a, b): return [{"player_tag":"#P1","player_name":"Alpha","violations":2}]
    monkeypatch.setattr(StatsService, "violation_counter_reset_options", opts)
    state = FakeState(); start = FakeMessage("♻️ Сбросить счетчик нарушений", user_id=1)
    await reset_violation_counter_start(start, state, app_context)
    msg = FakeMessage("1", user_id=1)
    await reset_violation_counter_selected(msg, state, app_context)
    assert state.state == str(ViolationStates.awaiting_reset_amount)
    assert "Сколько нарушений списать" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_reset_amount_keyboard_limits_buttons_to_active_count(app_context):
    state = FakeState(); await state.update_data(reset_player_options=[{"player_tag":"#P1","player_name":"Alpha","violations":2}])
    msg = FakeMessage("1", user_id=1)
    await reset_violation_counter_selected(msg, state, app_context)
    texts = [b.text for row in msg.answer.await_args.kwargs["reply_markup"].keyboard for b in row]
    assert "1" in texts and "2" in texts and "3" not in texts


@pytest.mark.asyncio
async def test_reset_amount_handler_reduces_counter_and_preserves_history(session, app_context):
    player, _ = await _seed_history(session, war_count=2, capital_count=0)
    state = FakeState(); await state.set_state(ViolationStates.awaiting_reset_amount); await state.update_data(reset_player_tag=player.player_tag, reset_player_name=player.name, reset_player_active_violations=2)
    msg = FakeMessage("1", user_id=1)
    await reset_violation_counter_amount_selected(msg, state, app_context)
    async with app_context.session_maker() as s:
        assert await ActiveViolationCounterService(s).count_for_player(player.player_tag, *_cycle()) == 1
        assert await s.scalar(select(func.count(Violation.id))) == 2


@pytest.mark.asyncio
async def test_reset_amount_handler_rejects_unavailable_amount(app_context):
    state = FakeState(); await state.set_state(ViolationStates.awaiting_reset_amount); await state.update_data(reset_player_tag="#P1", reset_player_name="Alpha", reset_player_active_violations=1)
    msg = FakeMessage("2", user_id=1)
    await reset_violation_counter_amount_selected(msg, state, app_context)
    assert "Выберите доступное" in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_reset_amount_back_returns_to_player_selection(app_context, monkeypatch):
    async def current_cycle(self): return SimpleNamespace(start=_cycle()[0], end=_cycle()[1])
    monkeypatch.setattr(PeriodService, "current_cycle", current_cycle)
    async def opts(self, a, b): return [{"player_tag":"#P2","player_name":"Bravo","violations":1}]
    monkeypatch.setattr(StatsService, "violation_counter_reset_options", opts)
    state = FakeState(); await state.set_state(ViolationStates.awaiting_reset_amount)
    msg = FakeMessage("⬅️ Назад", user_id=1)
    await reset_violation_counter_amount_selected(msg, state, app_context)
    assert state.state == str(ViolationStates.awaiting_reset_player_number)
    assert msg.answer.await_args.kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_non_admin_cannot_select_reset_amount(app_context):
    state = FakeState(); await state.set_state(ViolationStates.awaiting_reset_amount)
    msg = FakeMessage("1", user_id=999)
    await reset_violation_counter_amount_selected(msg, state, app_context)
    assert "Недостаточно прав" in msg.answer.await_args.args[0]
    assert state.state is None

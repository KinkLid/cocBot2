from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.bot.handlers.admin import (
    manual_claimed_target_attack_selected,
    manual_claimed_target_player_selected,
    manual_claimed_target_start,
)
from app.bot.keyboards.main import main_menu
from app.bot.states.manual_violation import ManualViolationStates
from app.models import Attack, PlayerAccount, Violation, War
from app.models.enums import ViolationCode, WarType
from app.services.dev_contribution import DevContributionService
from app.services.manual_violation import ManualViolationService
from app.services.war_sync import WarSyncService
from tests.fakes import FakeMessage, FakeState, FakeSender


@pytest.mark.asyncio
async def test_manual_flag_button_visible_for_admin_only():
    admin_flat = [b.text for row in main_menu(is_admin=True, is_registered=True).keyboard for b in row]
    user_flat = [b.text for row in main_menu(is_admin=False, is_registered=True).keyboard for b in row]
    assert "🚩 Чужой флажок" in admin_flat
    assert "🚩 Чужой флажок" not in user_flat


@pytest.mark.asyncio
async def test_manual_violation_flow(session, app_context):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    session.add(PlayerAccount(player_tag="#P2", name="Alpha", town_hall=16, current_clan_tag="#CLAN", current_clan_name="T", current_clan_rank=1, current_in_clan=True, last_seen_in_clan_at=now, first_absent_at=None, created_at=now, updated_at=now))
    war = War(war_uid="w1", clan_tag="#CLAN", clan_name="T", opponent_tag="#E", opponent_name="E", war_type=WarType.REGULAR, state="in_war", league_group_id=None, cwl_season=None, round_index=None, team_size=15, is_friendly=False, start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=5), preparation_start_time=now - timedelta(hours=23), source_payload={})
    session.add(war)
    await session.flush()
    attack = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P2", attacker_name="Alpha", attacker_position=20, attacker_town_hall=16, defender_tag="#E2", defender_name="Enemy2", defender_position=17, defender_town_hall=16, stars=3, destruction=100, attack_order=1, observed_at=now)
    session.add(attack)
    await session.commit()

    state = FakeState()
    start_msg = FakeMessage(text="🚩 Чужой флажок", user_id=1)
    await manual_claimed_target_start(start_msg, state, app_context)
    assert state.state == str(ManualViolationStates.awaiting_claimed_target_player)
    assert "⬅️ Назад" not in start_msg.answer.await_args.args[0]
    assert start_msg.answer.await_args.kwargs["reply_markup"].keyboard[0][0].text == "⬅️ Назад"

    bad_player_msg = FakeMessage(text="99", user_id=1)
    await manual_claimed_target_player_selected(bad_player_msg, state, app_context)
    assert "Нет игрока" in bad_player_msg.answer.await_args.args[0]

    choose_player_msg = FakeMessage(text="1", user_id=1)
    await manual_claimed_target_player_selected(choose_player_msg, state, app_context)
    assert state.state == str(ManualViolationStates.awaiting_claimed_target_attack)
    assert "⬅️ Назад" not in choose_player_msg.answer.await_args.args[0]
    assert choose_player_msg.answer.await_args.kwargs["reply_markup"].keyboard[0][0].text == "⬅️ Назад"

    back_to_players_msg = FakeMessage(text="⬅️ Назад", user_id=1)
    await manual_claimed_target_attack_selected(back_to_players_msg, state, app_context)
    assert state.state == str(ManualViolationStates.awaiting_claimed_target_player)
    assert "⬅️ Назад" not in back_to_players_msg.answer.await_args.args[0]
    assert back_to_players_msg.answer.await_args.kwargs["reply_markup"].keyboard[0][0].text == "⬅️ Назад"

    choose_player_msg = FakeMessage(text="1", user_id=1)
    await manual_claimed_target_player_selected(choose_player_msg, state, app_context)
    assert state.state == str(ManualViolationStates.awaiting_claimed_target_attack)

    bad_attack_msg = FakeMessage(text="foo", user_id=1)
    await manual_claimed_target_attack_selected(bad_attack_msg, state, app_context)
    assert "Введите номер атаки" in bad_attack_msg.answer.await_args.args[0]

    apply_msg = FakeMessage(text="1", user_id=1)
    await manual_claimed_target_attack_selected(apply_msg, state, app_context)
    assert state.state is None

    violation = await session.scalar(select(Violation).where(Violation.attack_id == attack.id))
    assert violation is not None
    assert violation.code == ViolationCode.CLAIMED_TARGET
    assert violation.is_manual is True
    assert violation.detected_at == now


@pytest.mark.asyncio
async def test_manual_violation_service_overwrites_existing(session, app_yaml_config):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    war = War(war_uid="w2", clan_tag="#CLAN", clan_name="T", opponent_tag="#E", opponent_name="E", war_type=WarType.REGULAR, state="in_war", league_group_id=None, cwl_season=None, round_index=None, team_size=15, is_friendly=False, start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=5), preparation_start_time=now - timedelta(hours=23), source_payload={})
    session.add(war)
    await session.flush()
    attack = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P2", attacker_name="Alpha", attacker_position=20, attacker_town_hall=16, defender_tag="#E2", defender_name="Enemy2", defender_position=17, defender_town_hall=16, stars=2, destruction=80, attack_order=1, observed_at=now)
    session.add(attack)
    await session.flush()
    session.add(Violation(attack_id=attack.id, war_id=war.id, player_tag="#P2", code=ViolationCode.ABOVE_SELF, reason_text="x", player_position=20, target_position=19, detected_at=now, is_manual=False))
    await session.commit()

    service = ManualViolationService(session, app_yaml_config)
    await service.apply_claimed_target_violation(attack.id, 1)
    await session.commit()

    assert await session.scalar(select(func.count(Violation.id)).where(Violation.attack_id == attack.id)) == 1
    v = await session.scalar(select(Violation).where(Violation.attack_id == attack.id))
    assert v.code == ViolationCode.CLAIMED_TARGET


@pytest.mark.asyncio
async def test_claimed_target_contribution_is_minus_50_and_keeps_baseline(session, app_yaml_config):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    session.add(PlayerAccount(player_tag="#P2", name="Alpha", town_hall=16, current_clan_tag="#CLAN", current_clan_name="T", current_clan_rank=1, current_in_clan=True, last_seen_in_clan_at=now, first_absent_at=None, created_at=now, updated_at=now))
    war = War(war_uid="w3", clan_tag="#CLAN", clan_name="T", opponent_tag="#E", opponent_name="E", war_type=WarType.REGULAR, state="war_ended", league_group_id=None, cwl_season=None, round_index=None, team_size=15, is_friendly=False, start_time=now - timedelta(hours=2), end_time=now - timedelta(hours=1), preparation_start_time=now - timedelta(hours=24), source_payload={})
    session.add(war)
    await session.flush()
    a1 = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P2", attacker_name="Alpha", attacker_position=20, attacker_town_hall=16, defender_tag="#E2", defender_name="Enemy2", defender_position=17, defender_town_hall=16, stars=3, destruction=100, attack_order=1, observed_at=now)
    a2 = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P2", attacker_name="Alpha", attacker_position=20, attacker_town_hall=16, defender_tag="#E2", defender_name="Enemy2", defender_position=17, defender_town_hall=16, stars=3, destruction=100, attack_order=2, observed_at=now + timedelta(minutes=1))
    session.add_all([a1, a2])
    await session.flush()
    session.add(Violation(attack_id=a1.id, war_id=war.id, player_tag="#P2", code=ViolationCode.CLAIMED_TARGET, reason_text="Атака по чужому флажку", player_position=20, target_position=17, detected_at=now, is_manual=True))
    await session.commit()

    ranking = await DevContributionService(session, app_yaml_config).build_contribution_ranking(type("P", (), {"start": now - timedelta(days=1), "end": now + timedelta(days=1)})())
    assert ranking[0].score == -42.0


@pytest.mark.asyncio
async def test_warsync_does_not_touch_manual_violation(session, fake_clash_client, app_yaml_config):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    war = War(war_uid="w4", clan_tag="#CLAN", clan_name="T", opponent_tag="#E", opponent_name="E", war_type=WarType.REGULAR, state="in_war", league_group_id=None, cwl_season=None, round_index=None, team_size=15, is_friendly=False, start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=2), preparation_start_time=now - timedelta(hours=23), source_payload={})
    session.add(war)
    await session.flush()
    attack = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P2", attacker_name="Alpha", attacker_position=20, attacker_town_hall=16, defender_tag="#E2", defender_name="Enemy2", defender_position=17, defender_town_hall=16, stars=2, destruction=80, attack_order=1, observed_at=now)
    session.add(attack)
    await session.flush()
    session.add(Violation(attack_id=attack.id, war_id=war.id, player_tag="#P2", code=ViolationCode.CLAIMED_TARGET, reason_text="Атака по чужому флажку", player_position=20, target_position=17, detected_at=now, is_manual=True))
    await session.commit()

    service = WarSyncService(session, fake_clash_client, app_yaml_config, type("N", (), {"notify_once": lambda *args, **kwargs: None})())
    await service._reconcile_violation(war, attack)
    v = await session.scalar(select(Violation).where(Violation.attack_id == attack.id))
    assert v.code == ViolationCode.CLAIMED_TARGET
    assert v.is_manual is True


@pytest.mark.asyncio
async def test_violation_enum_mapping_reads_lowercase_above_self(session):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    war = War(war_uid="w5", clan_tag="#CLAN", clan_name="T", opponent_tag="#E", opponent_name="E", war_type=WarType.REGULAR, state="in_war", league_group_id=None, cwl_season=None, round_index=None, team_size=15, is_friendly=False, start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=1), preparation_start_time=now - timedelta(hours=23), source_payload={})
    session.add(war)
    await session.flush()
    attack = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P5", attacker_name="Alpha", attacker_position=10, attacker_town_hall=16, defender_tag="#E5", defender_name="Enemy5", defender_position=9, defender_town_hall=16, stars=2, destruction=80, attack_order=1, observed_at=now)
    session.add(attack)
    await session.flush()
    await session.execute(
        Violation.__table__.insert().values(
            attack_id=attack.id,
            war_id=war.id,
            player_tag="#P5",
            code="above_self",
            reason_text="x",
            player_position=10,
            target_position=9,
            detected_at=now,
            is_manual=False,
        )
    )
    await session.commit()

    violation = await session.scalar(select(Violation).where(Violation.attack_id == attack.id))
    assert violation is not None
    assert violation.code == ViolationCode.ABOVE_SELF


@pytest.mark.asyncio
async def test_violation_enum_mapping_claimed_target_roundtrip(session):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    war = War(war_uid="w6", clan_tag="#CLAN", clan_name="T", opponent_tag="#E", opponent_name="E", war_type=WarType.REGULAR, state="in_war", league_group_id=None, cwl_season=None, round_index=None, team_size=15, is_friendly=False, start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=1), preparation_start_time=now - timedelta(hours=23), source_payload={})
    session.add(war)
    await session.flush()
    attack = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P6", attacker_name="Beta", attacker_position=11, attacker_town_hall=16, defender_tag="#E6", defender_name="Enemy6", defender_position=8, defender_town_hall=16, stars=3, destruction=100, attack_order=1, observed_at=now)
    session.add(attack)
    await session.flush()
    session.add(Violation(attack_id=attack.id, war_id=war.id, player_tag="#P6", code=ViolationCode.CLAIMED_TARGET, reason_text="manual", player_position=11, target_position=8, detected_at=now, is_manual=True))
    await session.commit()

    violation = await session.scalar(select(Violation).where(Violation.attack_id == attack.id))
    assert violation is not None
    assert violation.code == ViolationCode.CLAIMED_TARGET


@pytest.mark.asyncio
async def test_manual_claimed_target_player_selected_returns_error_on_service_exception(monkeypatch, app_context):
    state = FakeState()
    await state.set_state(ManualViolationStates.awaiting_claimed_target_player)
    await state.update_data(player_options=[{"player_tag": "#P2", "player_name": "Alpha"}])

    async def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ManualViolationService, "list_player_attacks_for_current_cycle", _raise)

    message = FakeMessage(text="1", user_id=1)
    await manual_claimed_target_player_selected(message, state, app_context)

    assert message.answer.await_args.args[0] == "⚠️ Не удалось загрузить атаки игрока. Попробуйте позже."
    assert state.state == str(ManualViolationStates.awaiting_claimed_target_player)


@pytest.mark.asyncio
async def test_manual_claimed_target_attack_selected_returns_error_and_clears_state(monkeypatch, app_context):
    state = FakeState()
    await state.set_state(ManualViolationStates.awaiting_claimed_target_attack)
    await state.update_data(attack_options=[{"attack_id": 123}])

    async def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ManualViolationService, "apply_claimed_target_violation", _raise)

    message = FakeMessage(text="1", user_id=1)
    await manual_claimed_target_attack_selected(message, state, app_context)

    assert message.answer.await_args.args[0] == "⚠️ Не удалось поставить нарушение. Попробуйте позже."
    assert state.state is None


@pytest.mark.asyncio
async def test_manual_claimed_target_excludes_cwl_attacks(session, app_yaml_config):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    war = War(war_uid="cwl-manual", clan_tag="#CLAN", clan_name="T", opponent_tag="#E", opponent_name="E", war_type=WarType.CWL, state="in_war", league_group_id="g", cwl_season="2026-05", round_index=0, team_size=15, is_friendly=False, start_time=now - timedelta(hours=1), end_time=now + timedelta(hours=2), preparation_start_time=now - timedelta(hours=23), source_payload={})
    session.add(war)
    await session.flush()
    attack = Attack(war_id=war.id, attacker_player_id=None, attacker_tag="#P2", attacker_name="Alpha", attacker_position=10, attacker_town_hall=16, defender_tag="#E2", defender_name="Enemy2", defender_position=1, defender_town_hall=16, stars=2, destruction=80, attack_order=1, observed_at=now)
    session.add(attack)
    await session.commit()

    service = ManualViolationService(session, app_yaml_config)
    attacks = await service.list_player_attacks_for_current_cycle("#P2")
    assert attacks == []
    with pytest.raises(ValueError, match="Для ЛВК ручные нарушения отключены"):
        await service.apply_claimed_target_violation(attack.id, 1)
    assert await session.scalar(select(Violation).where(Violation.attack_id == attack.id)) is None

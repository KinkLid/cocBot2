from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio

import pytest
from sqlalchemy import func, select

from app.models import Attack, Violation
from app.models.enums import ViolationCode, WarType
from app.schemas.dto import WarDTO
from app.services import war_sync as war_sync_module
from app.services.war_sync import WarSyncService
from tests.helpers import coc_time, make_enemy_roster


def _feliks_war(start: datetime, *, second_stars: int | None = None,
                shuffled_members: bool = False) -> WarDTO:
    attacks_by_member = {
        f"#C{position}": [{
            "defenderTag": f"#E{position:02d}", "stars": 3,
            "destructionPercentage": 100.0, "order": position - 10,
        }]
        for position in range(11, 17)
    }
    feliks_attacks = [{
        "defenderTag": "#E09", "stars": 3,
        "destructionPercentage": 100.0, "order": 7,
    }]
    if second_stars is not None:
        feliks_attacks.append({
            "defenderTag": "#E10", "stars": second_stars,
            "destructionPercentage": 100.0 if second_stars == 3 else 80.0,
            "order": 8,
        })
    members = [
        {
            "tag": f"#C{position}", "name": f"Closer{position}",
            "mapPosition": position, "townhallLevel": 16,
            "attacks": attacks_by_member[f"#C{position}"],
        }
        for position in range(11, 17)
    ] + [{
        "tag": "#F", "name": "FELIKS", "mapPosition": 13,
        "townhallLevel": 16, "attacks": feliks_attacks,
    }]
    if shuffled_members:
        members.reverse()
        for member in members:
            member["attacks"].reverse()
    return WarDTO.model_validate({
        "state": "inWar", "teamSize": 16, "attacksPerMember": 2,
        "preparationStartTime": coc_time(start - timedelta(days=1)),
        "startTime": coc_time(start), "endTime": coc_time(start + timedelta(days=1)),
        "isFriendly": False,
        "clan": {"tag": "#CLAN", "name": "Clan", "members": members},
        "opponent": {"tag": "#ENEMY", "name": "Enemy", "members": make_enemy_roster(16)},
        "clan_tag": "#CLAN", "war_type": "regular", "raw_payload": {},
    })


@pytest.mark.parametrize("team_size", [50, 25])
def test_reconcile_violation_uses_only_real_defender_positions(monkeypatch, team_size: int) -> None:
    service = WarSyncService.__new__(WarSyncService)
    service.wars = SimpleNamespace(
        get_violation_by_attack_id=AsyncMock(return_value=None),
        list_attacks_for_war=AsyncMock(return_value=[]),
        add_violation=AsyncMock(),
        delete_violation=AsyncMock(),
    )
    service.period_service = SimpleNamespace(current_cycle=AsyncMock())
    service.active_violation_counter = SimpleNamespace(count_for_player=AsyncMock(return_value=0))
    service.notifier = SimpleNamespace(notify_once=AsyncMock())
    service.session = SimpleNamespace(flush=AsyncMock())

    captured_positions: list[int] = []

    def fake_evaluate_attack_violation(**kwargs):
        captured_positions.extend(kwargs["defender_positions"])
        return SimpleNamespace(violated=False, code=None, reason_text=None)

    monkeypatch.setattr(war_sync_module, "evaluate_attack_violation", fake_evaluate_attack_violation)

    war = SimpleNamespace(
        id=1,
        is_friendly=False,
        war_type=WarType.REGULAR,
        start_time=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        team_size=team_size,
    )
    attack = SimpleNamespace(
        id=10,
        observed_at=datetime(2026, 4, 1, 11, 0, tzinfo=UTC),
        attacker_position=team_size - 1,
        defender_position=team_size,
        attacker_tag="#A",
    )

    asyncio.run(
        service._reconcile_violation(
            war,
            attack,
            defender_positions=list(range(1, team_size + 1)),
        )
    )

    assert captured_positions == list(range(1, team_size + 1))
    assert max(captured_positions) == team_size
    assert team_size + 1 not in captured_positions
    assert team_size + 2 not in captured_positions


@pytest.mark.asyncio
async def test_live_feliks_chain_stays_valid_across_repeated_syncs(
    session, fake_clash_client, app_yaml_config, monkeypatch
):
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    monkeypatch.setattr(war_sync_module, "utcnow", lambda: start + timedelta(hours=1))
    monkeypatch.setattr(
        "app.services.violation_recalculation.utcnow",
        lambda: start + timedelta(hours=1),
    )
    notifier = SimpleNamespace(notify_once=AsyncMock())
    service = WarSyncService(session, fake_clash_client, app_yaml_config, notifier)

    fake_clash_client.current_war = _feliks_war(start)
    await service.sync_all()
    assert await session.scalar(select(func.count(Violation.id))) == 0
    notifier.notify_once.assert_not_awaited()

    fake_clash_client.current_war = _feliks_war(start, second_stars=3)
    await service.sync_all()
    await service.sync_all()

    assert await session.scalar(select(func.count(Violation.id))) == 0
    assert await session.scalar(select(func.count(Attack.id))) == 8
    notifier.notify_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_feliks_failed_second_attack_finalizes_once(
    session, fake_clash_client, app_yaml_config, monkeypatch
):
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    monkeypatch.setattr(war_sync_module, "utcnow", lambda: start + timedelta(hours=1))
    monkeypatch.setattr(
        "app.services.violation_recalculation.utcnow",
        lambda: start + timedelta(hours=1),
    )
    notifier = SimpleNamespace(notify_once=AsyncMock())
    service = WarSyncService(session, fake_clash_client, app_yaml_config, notifier)

    fake_clash_client.current_war = _feliks_war(start)
    await service.sync_all()
    assert await session.scalar(select(func.count(Violation.id))) == 0
    notifier.notify_once.assert_not_awaited()

    fake_clash_client.current_war = _feliks_war(start, second_stars=2)
    await service.sync_all()
    violation = await session.scalar(select(Violation))
    attacks = list((await session.scalars(select(Attack).order_by(Attack.attack_order))).all())
    assert violation is not None
    assert violation.code == ViolationCode.ABOVE_SELF
    assert violation.attack_id == next(a.id for a in attacks if a.defender_position == 9)
    assert all(a.id != violation.attack_id for a in attacks if a.defender_position == 10)
    assert notifier.notify_once.await_count == 1

    await service.sync_all()
    assert await session.scalar(select(func.count(Violation.id))) == 1
    assert await session.scalar(select(func.count(Attack.id))) == 8
    assert notifier.notify_once.await_count == 1


@pytest.mark.asyncio
async def test_live_sync_uses_attack_order_not_dto_iteration_order(
    session, fake_clash_client, app_yaml_config, monkeypatch
):
    start = datetime(2026, 7, 19, 8, tzinfo=UTC)
    monkeypatch.setattr(war_sync_module, "utcnow", lambda: start + timedelta(hours=1))
    monkeypatch.setattr(
        "app.services.violation_recalculation.utcnow",
        lambda: start + timedelta(hours=1),
    )
    notifier = SimpleNamespace(notify_once=AsyncMock())
    service = WarSyncService(session, fake_clash_client, app_yaml_config, notifier)
    fake_clash_client.current_war = _feliks_war(
        start, second_stars=3, shuffled_members=True
    )

    await service.sync_all()

    attacks = list((await session.scalars(select(Attack).order_by(Attack.id))).all())
    assert attacks[0].attack_order == 8  # FELIKS is visited first in the DTO.
    assert [attack.attack_order for attack in attacks] != list(range(1, 9))
    assert await session.scalar(select(func.count(Violation.id))) == 0
    notifier.notify_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_war_keeps_typed_attacks_per_member_with_empty_raw_payload(
    session, fake_clash_client, app_yaml_config
):
    dto = _feliks_war(datetime(2026, 7, 19, 8, tzinfo=UTC))
    assert dto.raw_payload == {}
    assert dto.attacks_per_member == 2
    service = WarSyncService(
        session, fake_clash_client, app_yaml_config,
        SimpleNamespace(notify_once=AsyncMock()),
    )

    war = await service._persist_war(dto)

    assert war.source_payload["attacksPerMember"] == 2

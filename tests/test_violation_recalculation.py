from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Attack, CycleBoundary, Violation, War, WarParticipant
from app.models.enums import ViolationCode, WarState, WarType
from app.services.violation_recalculation import ViolationRecalculationService


START = datetime(2026, 7, 19, 8, tzinfo=UTC)


async def _seed_war(session, *, start=START, uid="war", cwl=False):
    war = War(
        war_uid=uid, clan_tag="#CLAN", clan_name="Clan", opponent_tag="#ENEMY",
        opponent_name="Enemy", war_type=WarType.CWL if cwl else WarType.REGULAR,
        state=WarState.WAR_ENDED, team_size=30, is_friendly=False, start_time=start,
        end_time=start + timedelta(days=1), preparation_start_time=start - timedelta(days=1),
        source_payload={},
    )
    session.add(war)
    await session.flush()
    session.add_all([
        WarParticipant(war_id=war.id, player_tag=f"#E{position}", name=f"E{position}",
                       map_position=position, town_hall=16, is_own_clan=False)
        for position in range(1, 31)
    ])
    return war


async def _attack(session, war, position, seen, *, stars=3, attacker=13):
    attack = Attack(
        war_id=war.id, attacker_tag="#F", attacker_name="FELIKS", attacker_position=attacker,
        attacker_town_hall=16, defender_tag=f"#E{position}", defender_name=f"E{position}",
        defender_position=position, defender_town_hall=16, stars=stars, destruction=100,
        attack_order=position, observed_at=seen,
    )
    session.add(attack)
    await session.flush()
    return attack


async def _violation(session, war, attack, code=ViolationCode.ABOVE_SELF, *, manual=False):
    row = Violation(attack_id=attack.id, war_id=war.id, player_tag=attack.attacker_tag,
                    code=code, reason_text="old", player_position=attack.attacker_position,
                    target_position=attack.defender_position, detected_at=attack.observed_at,
                    is_manual=manual)
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_recalculation_feliks_removes_only_wrong_automatic_violation(session, monkeypatch):
    session.add(CycleBoundary(source_key="cycle", boundary_at=START - timedelta(days=1), description="cycle"))
    war = await _seed_war(session)
    before = START + timedelta(hours=1)
    for position in range(12, 17):
        await _attack(session, war, position, before, attacker=position)
    nine = await _attack(session, war, 9, before + timedelta(minutes=1))
    ten = await _attack(session, war, 10, before + timedelta(minutes=2))
    v9 = await _violation(session, war, nine)
    await _violation(session, war, ten)
    await session.commit()
    monkeypatch.setattr("app.services.period.utcnow", lambda: START + timedelta(days=2))

    result = await ViolationRecalculationService(session).recalculate_current_cycle()
    await session.commit()
    rows = list((await session.scalars(select(Violation).order_by(Violation.id))).all())

    assert [(row.attack_id, row.code) for row in rows] == [(v9.attack_id, ViolationCode.ABOVE_SELF)]
    assert (result.deleted, result.created) == (1, 0)


@pytest.mark.asyncio
async def test_recalculation_creates_updates_and_preserves_non_positional(session, monkeypatch):
    session.add(CycleBoundary(source_key="cycle", boundary_at=START - timedelta(days=1), description="cycle"))
    war = await _seed_war(session)
    missing = await _attack(session, war, 1, START + timedelta(minutes=1))
    changed = await _attack(session, war, 30, START + timedelta(minutes=2))
    await _violation(session, war, changed, ViolationCode.ABOVE_SELF)
    manual = await _attack(session, war, 2, START + timedelta(minutes=3))
    manual_row = await _violation(session, war, manual, manual=True)
    claimed = await _attack(session, war, 3, START + timedelta(minutes=4))
    claimed_row = await _violation(session, war, claimed, ViolationCode.CLAIMED_TARGET)
    await session.commit()
    monkeypatch.setattr("app.services.period.utcnow", lambda: START + timedelta(days=2))

    result = await ViolationRecalculationService(session).recalculate_current_cycle()
    await session.commit()

    assert result.created == 1
    assert result.updated == 1
    assert (await session.scalar(select(Violation).where(Violation.attack_id == missing.id))).code == ViolationCode.ABOVE_SELF
    assert (await session.scalar(select(Violation).where(Violation.attack_id == changed.id))).code == ViolationCode.TOO_LOW
    assert manual_row.is_manual is True
    assert claimed_row.code == ViolationCode.CLAIMED_TARGET


@pytest.mark.asyncio
async def test_recalculation_only_processes_regular_wars_in_current_cycle(session, monkeypatch):
    session.add(CycleBoundary(source_key="cycle", boundary_at=START - timedelta(days=1), description="cycle"))
    current = await _seed_war(session, uid="current")
    old = await _seed_war(session, uid="old", start=START - timedelta(days=2))
    cwl = await _seed_war(session, uid="cwl", cwl=True)
    await _attack(session, current, 1, START + timedelta(minutes=1))
    await _attack(session, old, 1, START - timedelta(days=2) + timedelta(minutes=1))
    await _attack(session, cwl, 1, START + timedelta(minutes=1))
    await session.commit()
    monkeypatch.setattr("app.services.period.utcnow", lambda: START + timedelta(days=2))

    result = await ViolationRecalculationService(session).recalculate_current_cycle()

    assert (result.wars_processed, result.attacks_checked, result.created) == (1, 1, 1)


@pytest.mark.asyncio
async def test_recalculation_sorts_mixed_naive_and_aware_observed_at(session, monkeypatch):
    session.add(CycleBoundary(source_key="cycle", boundary_at=START - timedelta(days=1), description="cycle"))
    war = await _seed_war(session)
    first = await _attack(session, war, 12, START + timedelta(minutes=2))
    await _attack(session, war, 13, (START + timedelta(minutes=1)).replace(tzinfo=None))
    await session.commit()
    # SQLite reloads datetimes without timezone information; retain one aware value
    # in the same ORM collection to reproduce mixed application/persisted values.
    first.observed_at = START + timedelta(minutes=2)
    monkeypatch.setattr("app.services.period.utcnow", lambda: START + timedelta(days=2))

    result = await ViolationRecalculationService(session).recalculate_current_cycle()

    assert result.attacks_checked == 2


@pytest.mark.asyncio
async def test_recalculation_uses_id_to_order_attacks_at_same_time(session, monkeypatch):
    session.add(CycleBoundary(source_key="cycle", boundary_at=START - timedelta(days=1), description="cycle"))
    war = await _seed_war(session)
    seen = START + timedelta(hours=1)
    for position in range(12, 17):
        await _attack(session, war, position, seen - timedelta(minutes=1), attacker=position)
    first = await _attack(session, war, 10, seen, attacker=13)
    second = await _attack(session, war, 9, seen, attacker=13)
    await session.commit()
    monkeypatch.setattr("app.services.period.utcnow", lambda: START + timedelta(days=2))

    await ViolationRecalculationService(session).recalculate_current_cycle()

    assert first.id < second.id
    assert await session.scalar(select(Violation).where(Violation.attack_id == second.id)) is None

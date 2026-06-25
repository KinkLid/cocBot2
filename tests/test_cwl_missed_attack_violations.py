from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, inspect, select

from app.models import CapitalRaidViolation, PlayerAccount, Violation
from app.models.enums import ViolationCode, WarType
from app.services.active_violation_counter import ActiveViolationCounterService
from app.services.dev_contribution import ContributionRankingRow, DevContributionService
from app.services.stats import StatsService
from app.services.war_sync import WarSyncService
from tests.helpers import make_cwl_war, make_regular_war


def test_cwl_missed_attack_is_regular_violation_code() -> None:
    assert ViolationCode.CWL_MISSED_ATTACK.value == "cwl_missed_attack"


def test_no_separate_cwl_violation_table_or_model_is_used() -> None:
    assert not Path("app/models/cwl_missed_attack_violation.py").exists()
    assert not Path("app/repositories/cwl_missed_attack_violation.py").exists()
    assert not Path("app/services/cwl_missed_attack_violation.py").exists()
    assert Violation.__tablename__ == "violations"


def test_cwl_missed_attack_is_stored_in_violations_table() -> None:
    columns = Violation.__table__.columns
    assert columns.attack_id.nullable is True
    assert columns.target_position.nullable is True
    assert "uq_violations_cwl_missed_attack_per_war_player" in {idx.name for idx in Violation.__table__.indexes}


async def _seed_player(session, tag="#P2", name="Alpha"):
    now = datetime(2026, 4, 1, tzinfo=UTC)
    session.add(PlayerAccount(player_tag=tag, name=name, town_hall=16, current_clan_tag="#CLAN", current_clan_name="Clan", current_clan_rank=1, current_in_clan=True, last_seen_in_clan_at=now, created_at=now, updated_at=now))
    await session.commit()


def _ended_cwl(start=None, *, tag="#P2", round_index=0, with_attack=False):
    dto = make_cwl_war(start=start or datetime(2026, 4, 1, 10, tzinfo=UTC), attacker_position=5, defender_position=5, round_index=round_index, attacker_tag=tag)
    dto.state = "warEnded"
    if not with_attack:
        dto.clan.members[0].attacks = []
    return dto


async def _service(session, fake_clash_client, app_yaml_config):
    notifier = SimpleNamespace(notify_once=AsyncMock())
    svc = WarSyncService(session, fake_clash_client, app_yaml_config, notifier)
    svc.period_service.current_cycle = AsyncMock(return_value=SimpleNamespace(start=datetime(2026, 4, 1, tzinfo=UTC), end=datetime(2026, 5, 1, tzinfo=UTC)))
    return svc, notifier


async def _persist_missed(session, fake_clash_client, app_yaml_config, dto=None):
    await _seed_player(session, tag=(dto.clan.members[0].tag if dto else "#P2"))
    svc, notifier = await _service(session, fake_clash_client, app_yaml_config)
    await svc._persist_war(dto or _ended_cwl())
    await session.commit()
    return svc, notifier


@pytest.mark.asyncio
async def test_ended_cwl_without_attack_creates_regular_violation(session, fake_clash_client, app_yaml_config):
    await _persist_missed(session, fake_clash_client, app_yaml_config)
    violation = await session.scalar(select(Violation))
    assert isinstance(violation, Violation)
    assert violation.attack_id is None
    assert violation.code == ViolationCode.CWL_MISSED_ATTACK
    assert violation.reason_text == "Не использовал атаку в ЛВК"
    assert violation.target_position is None


@pytest.mark.asyncio
async def test_cwl_with_attack_does_not_create_missed_attack_violation(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    svc, _ = await _service(session, fake_clash_client, app_yaml_config)
    await svc._persist_war(_ended_cwl(with_attack=True)); await session.commit()
    assert await session.scalar(select(func.count(Violation.id))) == 0


@pytest.mark.asyncio
async def test_active_cwl_without_attack_does_not_create_violation_before_end(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    dto = _ended_cwl(); dto.state = "inWar"
    svc, _ = await _service(session, fake_clash_client, app_yaml_config)
    await svc._persist_war(dto); await session.commit()
    assert await session.scalar(select(func.count(Violation.id))) == 0


@pytest.mark.asyncio
async def test_regular_war_without_attack_does_not_create_cwl_missed_violation(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    dto = make_regular_war(start=datetime(2026, 4, 1, 10, tzinfo=UTC), include_attack=False); dto.state="warEnded"
    svc, _ = await _service(session, fake_clash_client, app_yaml_config)
    await svc._persist_war(dto); await session.commit()
    assert await session.scalar(select(func.count(Violation.id))) == 0


@pytest.mark.asyncio
async def test_repeated_sync_creates_only_one_regular_violation(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    svc, _ = await _service(session, fake_clash_client, app_yaml_config)
    dto = _ended_cwl()
    await svc._persist_war(dto); await svc._persist_war(dto); await session.commit()
    assert await session.scalar(select(func.count(Violation.id))) == 1


@pytest.mark.asyncio
async def test_repeated_sync_does_not_repeat_notification(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    svc, notifier = await _service(session, fake_clash_client, app_yaml_config)
    dto = _ended_cwl()
    await svc._persist_war(dto); await svc._persist_war(dto)
    assert notifier.notify_once.await_count == 1


@pytest.mark.asyncio
async def test_late_visible_attack_removes_stale_violation(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    svc, _ = await _service(session, fake_clash_client, app_yaml_config)
    await svc._persist_war(_ended_cwl(with_attack=False))
    assert await session.scalar(select(func.count(Violation.id))) == 1
    await svc._persist_war(_ended_cwl(with_attack=True)); await session.commit()
    assert await session.scalar(select(func.count(Violation.id))) == 0


@pytest.mark.asyncio
async def test_seven_missed_cwl_rounds_create_seven_regular_violations(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    svc, _ = await _service(session, fake_clash_client, app_yaml_config)
    for i in range(7):
        await svc._persist_war(_ended_cwl(start=datetime(2026, 4, 1 + i, 10, tzinfo=UTC), round_index=i))
    await session.commit()
    assert await session.scalar(select(func.count(Violation.id))) == 7


@pytest.mark.asyncio
async def test_cwl_missed_attack_increases_normal_active_counter(session, fake_clash_client, app_yaml_config):
    await _persist_missed(session, fake_clash_client, app_yaml_config)
    assert await ActiveViolationCounterService(session).count_for_player("#P2", datetime(2026,4,1,tzinfo=UTC), datetime(2026,5,1,tzinfo=UTC)) == 1


@pytest.mark.asyncio
async def test_three_cwl_missed_attacks_add_existing_contribution_cross(session, fake_clash_client, app_yaml_config):
    await _seed_player(session)
    svc, _ = await _service(session, fake_clash_client, app_yaml_config)
    for i in range(3):
        await svc._persist_war(_ended_cwl(start=datetime(2026, 4, 1 + i, 10, tzinfo=UTC), round_index=i))
    count = await ActiveViolationCounterService(session).count_for_player("#P2", datetime(2026,4,1,tzinfo=UTC), datetime(2026,5,1,tzinfo=UTC))
    assert "❌" in DevContributionService(session, app_yaml_config).format_contribution_ranking([ContributionRankingRow("#P2","Alpha",1,100,False,count)])


@pytest.mark.asyncio
async def test_cwl_missed_attack_appears_in_normal_violation_history(session, fake_clash_client, app_yaml_config):
    await _persist_missed(session, fake_clash_client, app_yaml_config)
    text = await StatsService(session, app_yaml_config).build_player_violations_report(datetime(2026,4,1,tzinfo=UTC), datetime(2026,5,1,tzinfo=UTC), "#P2", "Alpha")
    assert "ЛВК | пропуск атаки" in text and "cwl_missed_attack" in text


@pytest.mark.asyncio
async def test_partial_reset_does_not_remove_cwl_missed_violation(session, fake_clash_client, app_yaml_config):
    await _persist_missed(session, fake_clash_client, app_yaml_config)
    remaining = await ActiveViolationCounterService(session).reduce_for_player(player_tag="#P2", cycle_start=datetime(2026,4,1,tzinfo=UTC), cycle_end=datetime(2026,5,1,tzinfo=UTC), amount=1, admin_telegram_id=1, reset_at=datetime(2026,4,10,tzinfo=UTC))
    await session.commit()
    assert remaining == 0
    assert await session.scalar(select(func.count(Violation.id))) == 1
    assert await session.scalar(select(func.count(CapitalRaidViolation.id))) == 0


@pytest.mark.asyncio
async def test_cwl_notification_contains_normal_active_violation_number(session, fake_clash_client, app_yaml_config):
    _, notifier = await _persist_missed(session, fake_clash_client, app_yaml_config)
    assert "Нарушение №1" in notifier.notify_once.await_args.kwargs["text"]

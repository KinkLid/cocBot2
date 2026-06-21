from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio

import pytest

from app.models.enums import WarType
from app.services import war_sync as war_sync_module
from app.services.war_sync import WarSyncService


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

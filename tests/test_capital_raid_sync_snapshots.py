from __future__ import annotations

from sqlalchemy import select
import pytest

from app.models import CapitalRaidParticipant, CapitalRaidViolation
from app.schemas.dto import CapitalRaidSeasonDTO, PlayerProfileDTO
from app.services.capital_raid_sync import CapitalRaidSyncService


@pytest.mark.asyncio
async def test_sync_saves_nested_destruction_and_weekend_violations(
    session, fake_clash_client, app_yaml_config
):
    fake_clash_client.capital_raid_seasons = [
        CapitalRaidSeasonDTO.model_validate(
            {
                "state": "ended",
                "startTime": "20260520T000000.000Z",
                "endTime": "20260523T000000.000Z",
                "members": [
                    {"tag": "#P4", "name": "Four", "attacks": 4, "attackLimit": 6},
                    {"tag": "#P5", "name": "Five", "attacks": 5, "attackLimit": 6},
                ],
                "attackLog": [
                    {
                        "districts": [
                            {
                                "attacks": [
                                    {"attackerTag": "#P4", "destructionPercent": 84},
                                    {"attackerTag": "#P4", "destructionPercent": 100},
                                    {"attackerTag": "#P5", "destructionPercent": 63},
                                    {"attackerTag": "#P5", "destructionPercent": 75},
                                    {"attackerTag": "#P5", "destructionPercent": 40},
                                ]
                            }
                        ]
                    }
                ],
            }
        )
    ]
    fake_clash_client.players = {
        "#P4": PlayerProfileDTO(tag="#P4", name="Four", townHallLevel=16),
        "#P5": PlayerProfileDTO(tag="#P5", name="Five", townHallLevel=16),
    }

    await CapitalRaidSyncService(session, fake_clash_client, app_yaml_config).sync_finished()

    participants = {
        participant.player_tag: participant
        for participant in (await session.execute(select(CapitalRaidParticipant))).scalars()
    }
    violations = list((await session.execute(select(CapitalRaidViolation))).scalars())
    assert participants["#P4"].total_destruction_percent == 184
    assert participants["#P5"].total_destruction_percent == 178
    assert [(violation.player_tag, violation.code, violation.attacks) for violation in violations] == [
        ("#P4", "capital_under_5_attacks", 4)
    ]


@pytest.mark.asyncio
async def test_sync_recalculates_violations_idempotently(session, fake_clash_client, app_yaml_config):
    season = CapitalRaidSeasonDTO.model_validate(
        {
            "state": "ended",
            "startTime": "20260520T000000.000Z",
            "endTime": "20260523T000000.000Z",
            "members": [{"tag": "#P1", "name": "Player", "attacks": 4}],
        }
    )
    fake_clash_client.capital_raid_seasons = [season]
    fake_clash_client.players["#P1"] = PlayerProfileDTO(tag="#P1", name="Player", townHallLevel=16)
    service = CapitalRaidSyncService(session, fake_clash_client, app_yaml_config)
    await service.sync_finished()
    season.members[0].attacks = 5
    await service.sync_finished()
    violations = list((await session.execute(select(CapitalRaidViolation))).scalars())
    assert violations == []

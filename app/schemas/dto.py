from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ViolationCode, WarType


class ClanMemberDTO(BaseModel):
    tag: str
    name: str
    town_hall: int = Field(default=1, alias="townHallLevel")
    clan_rank: int = Field(default=0, alias="clanRank")

    model_config = {"populate_by_name": True}


class PlayerProfileDTO(BaseModel):
    tag: str
    name: str
    town_hall: int = Field(default=1, alias="townHallLevel")

    model_config = {"populate_by_name": True}


class WarAttackDTO(BaseModel):
    defender_tag: str = Field(alias="defenderTag")
    stars: int
    destruction_percentage: float = Field(alias="destructionPercentage")
    order: int

    model_config = {"populate_by_name": True}


class WarMemberDTO(BaseModel):
    tag: str
    name: str
    map_position: int = Field(alias="mapPosition")
    town_hall_level: int = Field(alias="townhallLevel")
    attacks: list[WarAttackDTO] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WarClanSideDTO(BaseModel):
    tag: str
    name: str
    members: list[WarMemberDTO] = Field(default_factory=list)


class WarDTO(BaseModel):
    state: str
    clan: WarClanSideDTO
    opponent: WarClanSideDTO
    team_size: int = Field(alias="teamSize")
    preparation_start_time: str | None = Field(default=None, alias="preparationStartTime")
    start_time: str | None = Field(default=None, alias="startTime")
    end_time: str | None = Field(default=None, alias="endTime")
    is_friendly: bool = Field(default=False, alias="isFriendly")
    clan_tag: str
    war_type: WarType
    league_group_id: str | None = None
    cwl_season: str | None = None
    round_index: int | None = None
    raw_payload: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class CWLGroupDTO(BaseModel):
    state: str
    season: str
    rounds: list[dict]
    clan_tag: str
    league_group_id: str


class PeriodDTO(BaseModel):
    label: str
    start: datetime
    end: datetime


class PlayerStatsDTO(BaseModel):
    player_tag: str
    player_name: str
    town_hall: int
    telegram_id: int | None
    telegram_username: str | None
    registered_at: datetime | None
    wars: int
    attacks: int
    stars: int
    violations: int
    place: int
    clan_rank: int | None


class AttackExportDTO(BaseModel):
    observed_at: datetime
    war_type: WarType
    is_cwl: bool
    attacker_position: int
    defender_position: int
    attacker_town_hall: int
    defender_town_hall: int
    stars: int
    destruction: float
    violated: bool
    violation_code: ViolationCode | None
    violation_reason: str | None
    attacker_tag: str
    defender_tag: str
    attacker_name: str
    defender_name: str


class WarParticipationExportDTO(BaseModel):
    war_uid: str
    war_type: WarType
    start_time: datetime | None
    end_time: datetime | None
    roster_position: int
    attacks: list[AttackExportDTO] = Field(default_factory=list)


class PlayerExportDTO(BaseModel):
    player_tag: str
    player_name: str
    town_hall: int
    telegram_id: int | None
    telegram_username: str | None
    registered_at: datetime | None
    wars: int
    attacks: int
    stars: int
    violations: int
    place: int
    participation: list[WarParticipationExportDTO] = Field(default_factory=list)

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.enums import WarType
from app.schemas.dto import CWLGroupDTO, ClanMemberDTO, PlayerProfileDTO, WarDTO


def make_player_profile(tag: str, name: str, town_hall: int = 16) -> PlayerProfileDTO:
    return PlayerProfileDTO(tag=tag, name=name, townHallLevel=town_hall)


def make_clan_member(tag: str, name: str, rank: int, town_hall: int = 16) -> ClanMemberDTO:
    return ClanMemberDTO(tag=tag, name=name, clanRank=rank, townHallLevel=town_hall)


def coc_time(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%S.000Z")


def make_regular_war(*, start: datetime, attack_order: int = 1, attacker_position: int = 12, defender_position: int = 15, stars: int = 2, include_attack: bool = True) -> WarDTO:
    own_member = {
        "tag": "#P2",
        "name": "Alpha",
        "mapPosition": attacker_position,
        "townhallLevel": 16,
        "attacks": ([{"defenderTag": "#E2", "stars": stars, "destructionPercentage": 80.0, "order": attack_order}] if include_attack else []),
    }
    enemy_member = {
        "tag": "#E2",
        "name": "Enemy2",
        "mapPosition": defender_position,
        "townhallLevel": 16,
        "attacks": [],
    }
    payload = {
        "state": "inWar",
        "teamSize": 15,
        "preparationStartTime": coc_time(start - timedelta(hours=23)),
        "startTime": coc_time(start),
        "endTime": coc_time(start + timedelta(hours=24)),
        "isFriendly": False,
        "clan": {"tag": "#CLAN", "name": "TestClan", "members": [own_member]},
        "opponent": {"tag": "#ENEMY", "name": "EnemyClan", "members": [enemy_member]},
        "clan_tag": "#CLAN",
        "war_type": "regular",
        "raw_payload": {},
    }
    dto = WarDTO.model_validate(payload)
    dto.raw_payload = payload
    return dto


def make_cwl_war(
    *,
    start: datetime,
    attacker_position: int,
    defender_position: int,
    round_index: int,
    attacker_tag: str = "#P2",
    attacker_name: str = "Alpha",
    defender_tag: str = "#E2",
    defender_name: str = "Enemy2",
    attack_order: int = 1,
) -> WarDTO:
    dto = make_regular_war(
        start=start,
        attack_order=attack_order,
        attacker_position=attacker_position,
        defender_position=defender_position,
        include_attack=True,
    )
    dto.war_type = WarType.CWL
    dto.round_index = round_index
    dto.league_group_id = "#CLAN:2026-04"
    dto.cwl_season = "2026-04"
    dto.clan.members[0].tag = attacker_tag
    dto.clan.members[0].name = attacker_name
    dto.clan.members[0].attacks[0].defender_tag = defender_tag
    dto.opponent.members[0].tag = defender_tag
    dto.opponent.members[0].name = defender_name
    return dto


def make_cwl_group(season: str, war_tags: list[str]) -> CWLGroupDTO:
    return CWLGroupDTO.model_validate(
        {
            "state": "inWar",
            "season": season,
            "rounds": [{"warTags": war_tags}],
            "clan_tag": "#CLAN",
            "league_group_id": f"#CLAN:{season}",
        }
    )

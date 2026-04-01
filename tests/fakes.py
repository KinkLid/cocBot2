from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from app.clients.clash import ClashApiClient
from app.schemas.dto import CWLGroupDTO, ClanMemberDTO, PlayerProfileDTO, WarDTO


class FakeClashApiClient(ClashApiClient):
    def __init__(self) -> None:
        self.verify_map: dict[tuple[str, str], bool] = {}
        self.players: dict[str, PlayerProfileDTO] = {}
        self.clan: dict[str, Any] = {"tag": "#CLAN", "name": "TestClan"}
        self.members: list[ClanMemberDTO] = []
        self.current_war: WarDTO | None = None
        self.cwl_group: CWLGroupDTO | None = None
        self.cwl_wars: dict[str, WarDTO] = {}

    async def verify_player_token(self, player_tag: str, token: str) -> bool:
        return self.verify_map.get((player_tag, token), False)

    async def get_player(self, player_tag: str) -> PlayerProfileDTO:
        return self.players[player_tag]

    async def get_clan(self, clan_tag: str) -> dict[str, Any]:
        return self.clan

    async def get_clan_members(self, clan_tag: str) -> list[ClanMemberDTO]:
        return self.members

    async def get_current_war(self, clan_tag: str) -> WarDTO | None:
        return self.current_war

    async def get_cwl_group(self, clan_tag: str) -> CWLGroupDTO | None:
        return self.cwl_group

    async def get_cwl_war(self, war_tag: str, *, clan_tag: str, league_group_id: str, season: str, round_index: int) -> WarDTO:
        return self.cwl_wars[war_tag]


@dataclass
class FakeSender:
    sent: list[tuple[int, str]] = field(default_factory=list)

    async def __call__(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeState:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.state: str | None = None

    async def clear(self) -> None:
        self._data.clear()
        self.state = None

    async def set_state(self, state: Any) -> None:
        self.state = str(state)

    async def update_data(self, **kwargs: Any) -> None:
        self._data.update(kwargs)

    async def get_data(self) -> dict[str, Any]:
        return dict(self._data)


class FakeMessage:
    def __init__(self, text: str, user_id: int = 100, username: str | None = "tester") -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, username=username)
        self.answer = AsyncMock()
        self.answer_document = AsyncMock()
        self.edit_text = AsyncMock()


class FakeCallback:
    def __init__(self, data: str, user_id: int = 100, username: str | None = "tester") -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, username=username)
        self.message = FakeMessage(text="callback", user_id=user_id, username=username)
        self.answer = AsyncMock()

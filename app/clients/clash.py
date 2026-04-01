from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import aiohttp
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.schemas.dto import CWLGroupDTO, ClanMemberDTO, PlayerProfileDTO, WarDTO
from app.utils.tag import encode_tag

logger = logging.getLogger(__name__)


class ClashApiError(RuntimeError):
    pass


class ClashApiClient(ABC):
    @abstractmethod
    async def verify_player_token(self, player_tag: str, token: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def get_player(self, player_tag: str) -> PlayerProfileDTO:
        raise NotImplementedError

    @abstractmethod
    async def get_clan(self, clan_tag: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_clan_members(self, clan_tag: str) -> list[ClanMemberDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_current_war(self, clan_tag: str) -> WarDTO | None:
        raise NotImplementedError

    @abstractmethod
    async def get_cwl_group(self, clan_tag: str) -> CWLGroupDTO | None:
        raise NotImplementedError

    @abstractmethod
    async def get_cwl_war(self, war_tag: str, *, clan_tag: str, league_group_id: str, season: str, round_index: int) -> WarDTO:
        raise NotImplementedError


class HttpClashApiClient(ClashApiClient):
    BASE_URL = "https://api.clashofclans.com/v1"

    def __init__(self, token: str, timeout_seconds: int = 20) -> None:
        self.token = token
        self.timeout_seconds = timeout_seconds
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "HttpClashApiClient":
        await self.start()
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        await self.close()

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        await self.start()
        assert self._session is not None

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception_type((aiohttp.ClientError, ClashApiError)),
            reraise=True,
        ):
            with attempt:
                url = f"{self.BASE_URL}{path}"
                async with self._session.request(method, url, json=json_body) as response:
                    if response.status == 404:
                        return None
                    if response.status >= 400:
                        text = await response.text()
                        logger.warning("Clash API error: %s %s -> %s", method, path, text)
                        raise ClashApiError(f"Clash API error {response.status}: {text}")
                    return await response.json()
        raise ClashApiError("Unreachable retry loop")

    async def verify_player_token(self, player_tag: str, token: str) -> bool:
        payload = await self._request("POST", f"/players/{encode_tag(player_tag)}/verifytoken", json_body={"token": token})
        return bool(payload and payload.get("status") == "ok")

    async def get_player(self, player_tag: str) -> PlayerProfileDTO:
        payload = await self._request("GET", f"/players/{encode_tag(player_tag)}")
        if payload is None:
            raise ClashApiError(f"Игрок {player_tag} не найден")
        return PlayerProfileDTO.model_validate(payload)

    async def get_clan(self, clan_tag: str) -> dict[str, Any]:
        payload = await self._request("GET", f"/clans/{encode_tag(clan_tag)}")
        if payload is None:
            raise ClashApiError(f"Клан {clan_tag} не найден")
        return payload

    async def get_clan_members(self, clan_tag: str) -> list[ClanMemberDTO]:
        payload = await self._request("GET", f"/clans/{encode_tag(clan_tag)}/members")
        items = payload.get("items", []) if payload else []
        return [ClanMemberDTO.model_validate(item) for item in items]

    def _build_war_dto(self, payload: dict[str, Any], *, clan_tag: str, war_type, league_group_id=None, season=None, round_index=None) -> WarDTO:
        return WarDTO.model_validate(
            {
                **payload,
                "clan_tag": clan_tag,
                "war_type": war_type,
                "league_group_id": league_group_id,
                "cwl_season": season,
                "round_index": round_index,
                "raw_payload": payload,
            }
        )

    async def get_current_war(self, clan_tag: str) -> WarDTO | None:
        payload = await self._request("GET", f"/clans/{encode_tag(clan_tag)}/currentwar")
        if payload is None or payload.get("state") == "notInWar":
            return None
        return self._build_war_dto(payload, clan_tag=clan_tag, war_type="regular")

    async def get_cwl_group(self, clan_tag: str) -> CWLGroupDTO | None:
        payload = await self._request("GET", f"/clans/{encode_tag(clan_tag)}/currentwar/leaguegroup")
        if payload is None or payload.get("state") == "notInWar":
            return None
        league_group_id = f"{clan_tag}:{payload.get('season')}"
        return CWLGroupDTO.model_validate({**payload, "clan_tag": clan_tag, "league_group_id": league_group_id})

    async def get_cwl_war(self, war_tag: str, *, clan_tag: str, league_group_id: str, season: str, round_index: int) -> WarDTO:
        payload = await self._request("GET", f"/clanwarleagues/wars/{encode_tag(war_tag)}")
        if payload is None:
            raise ClashApiError(f"Война ЛВК {war_tag} не найдена")
        return self._build_war_dto(
            payload,
            clan_tag=clan_tag,
            war_type="cwl",
            league_group_id=league_group_id,
            season=season,
            round_index=round_index,
        )

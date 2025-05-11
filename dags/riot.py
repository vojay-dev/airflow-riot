import asyncio
from datetime import datetime
from enum import Enum
from typing import List, Dict, Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Region(str, Enum):
    NORTH_AMERICA = "na1"

class RoutingValue(str, Enum):
    AMERICAS = "americas"

class Queue(str, Enum):
    RANKED_SOLO = "RANKED_SOLO_5x5"

class LeagueEntry(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    summoner_id: str
    league_points: int
    wins: int = 0
    losses: int = 0

class Summoner(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    id: str
    account_id: str
    puuid: str
    summoner_level: int

class Participant(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    puuid: str
    champion_id: int
    champion_name: str
    win: bool
    kills: int
    deaths: int
    assists: int
    total_damage_dealt_to_champions: int
    gold_earned: int
    vision_score: float
    total_minions_killed: int

class MatchInfo(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    game_creation: datetime
    game_duration: int
    game_mode: str
    game_type: str
    game_version: str
    map_id: int
    participants: List[Participant]

class MatchMetadata(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    data_version: int
    match_id: str
    participants: List[str]

class Match(BaseModel):
    metadata: MatchMetadata
    info: MatchInfo

class RiotApiClient:

    def __init__(
        self,
        api_key: str,
        region: str = Region.NORTH_AMERICA.value,
        routing: str = RoutingValue.AMERICAS.value,
        timeout: int = 10
    ):
        self.api_key = api_key
        self.region = region
        self.routing = routing
        self.timeout = timeout
        self.headers = {"X-Riot-Token": api_key}
        self.client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        retry_count = 0
        max_retries = 5

        while retry_count < max_retries:
            try:
                response = await self.client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_count += 1
                    print(f"Rate limit exceeded. Waiting 60 seconds... (Attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(60)
                else:
                    raise
            except Exception as e:
                raise

        raise Exception(f"Rate limit exceeded after {max_retries} retries")

    async def get_challenger_league(self, queue: str = Queue.RANKED_SOLO.value) -> List[LeagueEntry]:
        url = f"https://{self.region}.api.riotgames.com/lol/league/v4/challengerleagues/by-queue/{queue}"
        data = await self._get(url)
        return [LeagueEntry.model_validate(entry) for entry in data.get("entries", [])]

    async def get_summoner_by_id(self, summoner_id: str) -> Summoner:
        url = f"https://{self.region}.api.riotgames.com/lol/summoner/v4/summoners/{summoner_id}"
        data = await self._get(url)
        return Summoner.model_validate(data)

    async def get_top_players(self, count: int = 10) -> List[Summoner]:
        challenger_entries = await self.get_challenger_league()
        sorted_entries = sorted(challenger_entries, key=lambda entry: entry.league_points, reverse=True)
        top_entries = sorted_entries[:count]

        tasks = [self.get_summoner_by_id(entry.summoner_id) for entry in top_entries]
        return await asyncio.gather(*tasks)

    async def get_match_ids_by_puuid(self, puuid: str, count: int = 5, start: int = 0) -> List[str]:
        url = f"https://{self.routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        params = {"count": count, "start": start}
        return await self._get(url, params)

    async def get_match(self, match_id: str) -> Match:
        url = f"https://{self.routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        data = await self._get(url)
        return Match.model_validate(data)

    async def get_matches_for_summoners(self, summoners: List[Summoner], matches_per_summoner: int = 5) -> List[Match]:
        match_id_tasks = [
            self.get_match_ids_by_puuid(summoner.puuid, count=matches_per_summoner)
            for summoner in summoners
        ]

        all_match_ids = await asyncio.gather(*match_id_tasks)
        unique_match_ids = list(set(match_id for sublist in all_match_ids for match_id in sublist))

        match_tasks = [self.get_match(match_id) for match_id in unique_match_ids]
        return await asyncio.gather(*match_tasks)

async def example_usage():
    api_key = "YOUR-RIOT-API-KEY"

    async with RiotApiClient(api_key) as client:
        players = await client.get_top_players(count=3)
        matches = await client.get_matches_for_summoners(players, matches_per_summoner=1)
        print(matches)

if __name__ == "__main__":
    asyncio.run(example_usage())

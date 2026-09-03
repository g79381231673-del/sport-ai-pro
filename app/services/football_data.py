import os
from typing import Any

import httpx


class FootballAPIError(RuntimeError):
    pass


class FootballDataClient:
    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("API_FOOTBALL_KEY")
        if not self.api_key:
            raise FootballAPIError("API_FOOTBALL_KEY is not configured")

    async def get(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        headers = {"x-apisports-key": self.api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.BASE_URL}/{endpoint}", params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        errors = payload.get("errors") or {}
        if errors:
            raise FootballAPIError(str(errors))
        return payload.get("response") or []

    async def fixtures_by_date(self, date: str, league: int | None = None, season: int | None = None):
        params: dict[str, Any] = {"date": date}
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        return await self.get("fixtures", params)

    async def fixture(self, fixture_id: int):
        return await self.get("fixtures", {"id": fixture_id})

    async def head_to_head(self, team_a: int, team_b: int, last: int = 10):
        return await self.get("fixtures/headtohead", {"h2h": f"{team_a}-{team_b}", "last": last})

    async def injuries(self, fixture_id: int):
        return await self.get("injuries", {"fixture": fixture_id})

    async def lineups(self, fixture_id: int):
        return await self.get("fixtures/lineups", {"fixture": fixture_id})

    async def statistics(self, fixture_id: int):
        return await self.get("fixtures/statistics", {"fixture": fixture_id})

    async def predictions(self, fixture_id: int):
        return await self.get("predictions", {"fixture": fixture_id})

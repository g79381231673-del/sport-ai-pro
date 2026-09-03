import os
from typing import Any
import httpx

BASE_URL = "https://v3.football.api-sports.io"

class ApiFootballError(RuntimeError):
    pass

async def request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("API_FOOTBALL_KEY")
    if not key:
        raise ApiFootballError("API_FOOTBALL_KEY is not configured")
    headers = {"x-apisports-key": key}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{BASE_URL}/{endpoint}", params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    if data.get("errors"):
        raise ApiFootballError(str(data["errors"]))
    return data

async def find_fixtures(date: str, team: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"date": date}
    if team:
        params["team"] = team
    return await request("fixtures", params)

async def fixture(fixture_id: int) -> dict[str, Any]:
    return await request("fixtures", {"id": fixture_id})

async def h2h(team_a: int, team_b: int) -> dict[str, Any]:
    return await request("fixtures/headtohead", {"h2h": f"{team_a}-{team_b}"})

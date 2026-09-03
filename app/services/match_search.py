from datetime import date
from typing import Any

from .football_data import FootballDataClient


def _norm(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def score_match(fixture: dict[str, Any], query: str) -> int:
    home = fixture.get("teams", {}).get("home", {}).get("name", "")
    away = fixture.get("teams", {}).get("away", {}).get("name", "")
    q = _norm(query)
    score = 0
    if _norm(home) in q:
        score += 2
    if _norm(away) in q:
        score += 2
    if _norm(f"{home}{away}") in q or _norm(f"{away}{home}") in q:
        score += 2
    return score


async def find_matches(query: str, match_date: str, client: FootballDataClient) -> list[dict[str, Any]]:
    fixtures = await client.fixtures_by_date(match_date)
    ranked = sorted(fixtures, key=lambda f: score_match(f, query), reverse=True)
    return [f for f in ranked if score_match(f, query) > 0]


async def build_analysis_payload(fixture: dict[str, Any], client: FootballDataClient) -> dict[str, Any]:
    fixture_id = fixture["fixture"]["id"]
    home = fixture["teams"]["home"]
    away = fixture["teams"]["away"]

    # Only call endpoints that make sense for a pre-match analysis.
    h2h = await client.head_to_head(home["id"], away["id"], last=10)
    injuries = await client.injuries(fixture_id)
    predictions = await client.predictions(fixture_id)

    return {
        "fixture": fixture,
        "h2h_last_10": h2h,
        "injuries": injuries,
        "provider_prediction": predictions,
        "data_quality_note": "Missing provider fields are preserved as null/empty values; the model must not invent them.",
    }

from dataclasses import dataclass
from typing import Any


@dataclass
class MatchRequest:
    query: str
    sport: str = "football"


class AnalysisPipeline:
    """V1 orchestration layer: identify match, collect data, then analyze.

    The pipeline deliberately keeps bookmaker odds out of Stage 1. Odds are
    accepted only later from the user's screenshot.
    """

    def __init__(self, sports_client: Any, analyst: Any):
        self.sports_client = sports_client
        self.analyst = analyst

    async def stage1(self, request: MatchRequest) -> dict:
        match = await self.sports_client.identify_match(request.query, request.sport)
        if not match:
            return {"status": "skip", "reason": "Матч нельзя точно идентифицировать."}

        data = await self.sports_client.collect_match_data(match)
        return await self.analyst.pre_match(match, data)

    async def stage2(self, analysis: dict, screenshot_text: str) -> dict:
        # OCR/image understanding will be plugged in here. The important rule
        # is that the initial market is checked before alternatives are tested.
        return await self.analyst.check_bookmaker_line(analysis, screenshot_text)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AnalysisResult:
    status: str
    match: dict[str, Any]
    data: dict[str, Any]
    prompt: str


def build_analysis_prompt(match: dict[str, Any], data: dict[str, Any], system_prompt: str) -> str:
    """Create the model input while explicitly forbidding invented data."""
    return f"""{system_prompt}\n\nМАТЧ:\n{match}\n\nПОДТВЕРЖДЁННЫЕ ДАННЫЕ:\n{data}\n\nПравило: используй только переданные/подтверждённые данные. Если данных недостаточно, прямо укажи это. На ЭТАПЕ 1 коэффициенты не ищи и не используй. Выдай только один предварительный рынок с конкретной линией."""


def prepare_analysis(match: dict[str, Any], data: dict[str, Any], system_prompt: str) -> AnalysisResult:
    if not match or not match.get("fixture_id"):
        return AnalysisResult("skip", match, data, "")
    return AnalysisResult("ready", match, data, build_analysis_prompt(match, data, system_prompt))

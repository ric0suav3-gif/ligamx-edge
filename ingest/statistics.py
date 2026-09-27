from __future__ import annotations

from typing import Any

from .api_football import APIFootballClient

STAT_ALIASES = {
    "Total Shots": "shots",
    "Shots on Goal": "shots_on_target",
    "Corner Kicks": "corners",
    "Fouls": "fouls",
    "Yellow Cards": "yellow",
    "Red Cards": "red",
    "Offsides": "offsides",
    "Ball Possession": "possession",
}


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("%", "")
        if text in {"", "-"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def parse_fixture_statistics(
    rows: list[dict[str, Any]],
) -> dict[int, dict[str, float | None]]:
    """Convert API-Football fixture statistics into model-friendly fields.

    Missing values stay None; they are never coerced to zero.
    """
    result: dict[int, dict[str, float | None]] = {}

    for team_row in rows:
        team_id = team_row.get("team", {}).get("id")
        if team_id is None:
            continue

        stats: dict[str, float | None] = {}
        for item in team_row.get("statistics", []):
            name = STAT_ALIASES.get(item.get("type"))
            if not name:
                continue
            stats[name] = _to_number(item.get("value"))

        yellow = stats.get("yellow")
        red = stats.get("red")
        stats["cards"] = (
            None
            if yellow is None and red is None
            else (yellow or 0.0) + (red or 0.0)
        )
        result[int(team_id)] = stats

    return result


def fixture_statistics(
    client: APIFootballClient, fixture_id: int
) -> dict[int, dict[str, float | None]]:
    return parse_fixture_statistics(
        client.fixture_statistics(fixture_id).response
    )

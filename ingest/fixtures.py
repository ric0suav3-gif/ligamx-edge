from __future__ import annotations

from datetime import date
from typing import Any

from .api_football import APIFootballClient

UCL_LEAGUE_ID = 2
COMPLETED_STATUSES = {"FT", "AET", "PEN"}


def ucl_fixtures_for_date(
    client: APIFootballClient,
    day: date | str,
    season: int,
) -> list[dict[str, Any]]:
    day_str = day.isoformat() if isinstance(day, date) else str(day)
    return client.fixtures(
        league=UCL_LEAGUE_ID,
        season=season,
        date=day_str,
    ).response


def recent_team_fixtures(
    client: APIFootballClient,
    team_id: int,
    last: int = 30,
    league_id: int | None = None,
    season: int | None = None,
    completed_only: bool = True,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"team": team_id, "last": last}
    if league_id is not None:
        params["league"] = league_id
    if season is not None:
        params["season"] = season

    rows = client.fixtures(**params).response
    if not completed_only:
        return rows

    return [
        row
        for row in rows
        if row.get("fixture", {}).get("status", {}).get("short")
        in COMPLETED_STATUSES
    ]

from __future__ import annotations

from typing import Any

from .api_football import APIFootballClient, APIFootballError


def league_season_record(
    client: APIFootballClient, league_id: int, season: int
) -> dict[str, Any]:
    data = client.leagues(id=league_id, season=season)
    if not data.response:
        raise APIFootballError(
            f"No league record returned for league={league_id}, season={season}"
        )

    record = data.response[0]
    seasons = record.get("seasons", [])
    season_record = next((x for x in seasons if x.get("year") == season), None)
    if season_record is None:
        raise APIFootballError(
            f"League {league_id} exists, but season {season} was not returned"
        )
    return {"league": record.get("league", {}), "country": record.get("country", {}), **season_record}


def coverage_flags(
    client: APIFootballClient, league_id: int, season: int
) -> dict[str, Any]:
    return league_season_record(client, league_id, season).get("coverage", {})


def flatten_coverage(prefix: str, value: Any, out: dict[str, bool]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else key
            flatten_coverage(name, child, out)
    elif isinstance(value, bool):
        out[prefix] = value


def flat_coverage(
    client: APIFootballClient, league_id: int, season: int
) -> dict[str, bool]:
    out: dict[str, bool] = {}
    flatten_coverage("", coverage_flags(client, league_id, season), out)
    return out

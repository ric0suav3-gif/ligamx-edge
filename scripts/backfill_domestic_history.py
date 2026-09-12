from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import DOMESTIC_LEAGUES, MATCH_DATE, TEAMS
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from ingest.statistics import parse_fixture_statistics

COMPLETED = {"FT", "AET", "PEN"}
MODEL_STATS = (
    "shots",
    "shots_on_target",
    "corners",
    "fouls",
    "yellow",
    "red",
    "offsides",
    "possession",
    "cards",
)


def fixture_date(row: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(row["fixture"]["date"].replace("Z", "+00:00"))


def cached_fixtures(
    client: APIFootballClient,
    team_id: int,
    league_id: int,
    season: int,
) -> list[dict[str, Any]]:
    key = f"team_{team_id}_league_{league_id}_season_{season}"
    cached = load_json("fixture_lists", key)
    if cached is not None:
        return cached
    rows = client.fixtures(team=team_id, league=league_id, season=season).response
    save_json("fixture_lists", key, rows)
    return rows


def cached_stats(
    client: APIFootballClient,
    fixture_id: int,
) -> list[dict[str, Any]]:
    key = f"fixture_{fixture_id}"
    cached = load_json("fixture_stats", key)
    if cached is not None:
        return cached
    rows = client.fixture_statistics(fixture_id).response
    save_json("fixture_stats", key, rows)
    return rows


def perspective_row(
    fixture: dict[str, Any],
    team_id: int,
    stats_by_team: dict[int, dict[str, float | None]],
) -> dict[str, Any]:
    home = fixture["teams"]["home"]
    away = fixture["teams"]["away"]
    is_home = int(home["id"]) == team_id
    own = home if is_home else away
    opp = away if is_home else home

    goals = fixture.get("goals", {})
    goals_for = goals.get("home") if is_home else goals.get("away")
    goals_against = goals.get("away") if is_home else goals.get("home")

    own_stats = stats_by_team.get(team_id, {})
    opp_stats = stats_by_team.get(int(opp["id"]), {})

    return {
        "fixture_id": int(fixture["fixture"]["id"]),
        "date": fixture["fixture"]["date"],
        "season": fixture.get("league", {}).get("season"),
        "league_id": fixture.get("league", {}).get("id"),
        "league_name": fixture.get("league", {}).get("name"),
        "venue": "home" if is_home else "away",
        "team_id": team_id,
        "team_name": own.get("name"),
        "opponent_id": int(opp["id"]),
        "opponent_name": opp.get("name"),
        "goals_for": goals_for,
        "goals_against": goals_against,
        "stats_for": {stat: own_stats.get(stat) for stat in MODEL_STATS},
        "stats_against": {stat: opp_stats.get(stat) for stat in MODEL_STATS},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill recent domestic-league histories for today's UCL clubs."
    )
    parser.add_argument("--matches", type=int, default=30)
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=[2026, 2025, 2024, 2023],
        help="Season start years, newest first.",
    )
    parser.add_argument(
        "--cutoff",
        default=MATCH_DATE,
        help="Exclude fixtures on/after this YYYY-MM-DD date.",
    )
    args = parser.parse_args()

    cutoff = datetime.fromisoformat(args.cutoff + "T00:00:00+00:00")
    client = APIFootballClient()

    print(
        f"Backfilling up to {args.matches} domestic matches per team "
        f"before {args.cutoff}."
    )
    print("API responses are cached locally, so reruns do not re-spend calls.\n")

    for team_id, team_name in sorted(TEAMS.items(), key=lambda x: x[1]):
        league = DOMESTIC_LEAGUES[team_id]
        selected: list[dict[str, Any]] = []

        for season in args.seasons:
            rows = cached_fixtures(
                client,
                team_id=team_id,
                league_id=league["league_id"],
                season=season,
            )
            eligible = [
                row
                for row in rows
                if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
                and fixture_date(row) < cutoff
            ]
            eligible.sort(key=fixture_date, reverse=True)

            seen = {int(x["fixture"]["id"]) for x in selected}
            for row in eligible:
                fixture_id = int(row["fixture"]["id"])
                if fixture_id not in seen:
                    selected.append(row)
                    seen.add(fixture_id)
                if len(selected) >= args.matches:
                    break

            if len(selected) >= args.matches:
                break

        selected.sort(key=fixture_date)
        history: list[dict[str, Any]] = []
        missing = {stat: 0 for stat in MODEL_STATS}

        for idx, fixture in enumerate(selected, start=1):
            fixture_id = int(fixture["fixture"]["id"])
            raw_stats = cached_stats(client, fixture_id)
            stats_by_team = parse_fixture_statistics(raw_stats)
            row = perspective_row(fixture, team_id, stats_by_team)

            for stat in MODEL_STATS:
                if row["stats_for"].get(stat) is None:
                    missing[stat] += 1

            history.append(row)
            if idx % 10 == 0 or idx == len(selected):
                print(f"  {team_name}: stats {idx}/{len(selected)}")

        payload = {
            "team_id": team_id,
            "team_name": team_name,
            "domestic_league": league,
            "cutoff": args.cutoff,
            "requested_matches": args.matches,
            "matches": history,
        }
        path = save_json("domestic_history", str(team_id), payload)

        n = len(history)
        print(f"{team_name} ({team_id}) | {league['league_name']} | {n} matches")
        if n:
            for stat in ("shots", "shots_on_target", "corners", "fouls", "yellow"):
                good = n - missing[stat]
                print(f"  {stat}: {good}/{n} populated")
        print(f"  saved: {path}\n")


if __name__ == "__main__":
    main()

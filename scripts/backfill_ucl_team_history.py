from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import MATCH_DATE, TEAMS, UCL_LEAGUE_ID
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from ingest.statistics import parse_fixture_statistics

COMPLETED = {"FT", "AET", "PEN"}
STATS = (
    "shots",
    "shots_on_target",
    "corners",
    "fouls",
    "yellow",
    "red",
    "offsides",
    "cards",
)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def proper_ucl(row: dict[str, Any]) -> bool:
    round_name = str(row.get("league", {}).get("round") or "").lower()
    excluded = ("qualif", "prelim", "play-off", "playoff")
    return not any(token in round_name for token in excluded)


def cached_fixture_list(
    client: APIFootballClient,
    team_id: int,
    season: int,
) -> list[dict[str, Any]]:
    key = f"ucl_team_{team_id}_season_{season}"
    cached = load_json("ucl_team_fixture_lists", key)
    if cached is not None:
        return cached
    rows = client.fixtures(
        team=team_id,
        league=UCL_LEAGUE_ID,
        season=season,
    ).response
    save_json("ucl_team_fixture_lists", key, rows)
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


def perspective(
    row: dict[str, Any],
    team_id: int,
    parsed: dict[int, dict[str, float | None]],
) -> dict[str, Any]:
    home = row["teams"]["home"]
    away = row["teams"]["away"]
    is_home = int(home["id"]) == team_id
    own = home if is_home else away
    opp = away if is_home else home
    own_stats = parsed.get(team_id, {})
    opp_stats = parsed.get(int(opp["id"]), {})

    return {
        "fixture_id": int(row["fixture"]["id"]),
        "date": row["fixture"]["date"],
        "round": row.get("league", {}).get("round"),
        "venue": "home" if is_home else "away",
        "team_id": team_id,
        "team_name": own.get("name"),
        "opponent_id": int(opp["id"]),
        "opponent_name": opp.get("name"),
        "stats_for": {stat: own_stats.get(stat) for stat in STATS},
        "stats_against": {stat: opp_stats.get(stat) for stat in STATS},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill recent proper-stage UCL stat histories for today's clubs."
    )
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=[2026, 2025, 2024, 2023],
    )
    parser.add_argument("--cutoff", default=MATCH_DATE)
    args = parser.parse_args()

    cutoff = datetime.fromisoformat(args.cutoff + "T00:00:00+00:00")
    client = APIFootballClient()

    for team_id, team_name in sorted(TEAMS.items(), key=lambda x: x[1]):
        rows: list[dict[str, Any]] = []
        for season in args.seasons:
            rows.extend(cached_fixture_list(client, team_id, season))

        dedup = {
            int(row["fixture"]["id"]): row
            for row in rows
            if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
            and parse_dt(row["fixture"]["date"]) < cutoff
            and proper_ucl(row)
        }
        ordered = sorted(dedup.values(), key=lambda row: parse_dt(row["fixture"]["date"]))
        selected = ordered[-args.matches:] if args.matches > 0 else ordered

        history: list[dict[str, Any]] = []
        for idx, row in enumerate(selected, start=1):
            fixture_id = int(row["fixture"]["id"])
            parsed = parse_fixture_statistics(cached_stats(client, fixture_id))
            history.append(perspective(row, team_id, parsed))
            if idx % 10 == 0 or idx == len(selected):
                print(f"  {team_name}: stats {idx}/{len(selected)}")

        payload = {
            "team_id": team_id,
            "team_name": team_name,
            "cutoff": args.cutoff,
            "matches": history,
        }
        path = save_json("ucl_team_history", str(team_id), payload)

        print(f"{team_name:20s} | proper-stage UCL matches: {len(history)}")
        if history:
            for stat in ("shots", "shots_on_target", "corners"):
                n = sum(row["stats_for"].get(stat) is not None for row in history)
                print(f"  {stat}: {n}/{len(history)} populated")
        print(f"  saved: {path}\n")


if __name__ == "__main__":
    main()

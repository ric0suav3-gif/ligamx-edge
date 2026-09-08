from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.competitions import EUROPEAN_COMPETITIONS, UCL
from config.ucl_2026 import MATCH_DATE, TEAMS
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from model.elo import EloRatings
from model.ewma import ewma

COMPLETED = {"FT", "AET", "PEN"}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cached_competition_fixtures(
    client: APIFootballClient,
    league_id: int,
    season: int,
) -> list[dict[str, Any]]:
    key = f"competition_{league_id}_season_{season}"
    cached = load_json("european_fixture_lists", key)
    if cached is not None:
        return cached
    rows = client.fixtures(league=league_id, season=season).response
    save_json("european_fixture_lists", key, rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a cross-league club Elo from UEFA competition results."
    )
    parser.add_argument(
        "--seasons", type=int, nargs="+", default=[2023, 2024, 2025, 2026]
    )
    parser.add_argument("--cutoff", default=MATCH_DATE)
    parser.add_argument("--k", type=float, default=20.0)
    parser.add_argument("--home-advantage", type=float, default=55.0)
    parser.add_argument("--ucl-window", type=int, default=300)
    parser.add_argument("--ucl-half-life", type=float, default=180.0)
    args = parser.parse_args()

    cutoff = datetime.fromisoformat(args.cutoff + "T00:00:00+00:00")
    client = APIFootballClient()
    all_rows: list[dict[str, Any]] = []

    for competition_id, name in EUROPEAN_COMPETITIONS.items():
        for season in args.seasons:
            rows = cached_competition_fixtures(client, competition_id, season)
            good = [
                row for row in rows
                if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
                and parse_dt(row["fixture"]["date"]) < cutoff
                and row.get("goals", {}).get("home") is not None
                and row.get("goals", {}).get("away") is not None
            ]
            all_rows.extend(good)
            print(f"{name:26s} {season}: {len(good)} completed before cutoff")

    dedup = {
        int(row["fixture"]["id"]): row
        for row in all_rows
    }
    ordered = sorted(dedup.values(), key=lambda row: parse_dt(row["fixture"]["date"]))

    ratings = EloRatings(k=args.k, home_advantage=args.home_advantage)
    for row in ordered:
        home_id = int(row["teams"]["home"]["id"])
        away_id = int(row["teams"]["away"]["id"])
        ratings.update(
            home_id=home_id,
            away_id=away_id,
            home_goals=int(row["goals"]["home"]),
            away_goals=int(row["goals"]["away"]),
        )

    # UCL scoring environment used to transfer domestic rates onto a UCL baseline.
    ucl_rows = [
        row for row in ordered
        if int(row.get("league", {}).get("id") or 0) == UCL
    ][-args.ucl_window:]
    ucl_home = ewma(
        [float(row["goals"]["home"]) for row in ucl_rows],
        args.ucl_half_life,
    )
    ucl_away = ewma(
        [float(row["goals"]["away"]) for row in ucl_rows],
        args.ucl_half_life,
    )

    payload = {
        "meta": {
            "cutoff": args.cutoff,
            "seasons": args.seasons,
            "matches": len(ordered),
            "k": args.k,
            "home_advantage": args.home_advantage,
        },
        "ucl_baseline": {
            "n": len(ucl_rows),
            "home_goals": ucl_home,
            "away_goals": ucl_away,
            "half_life": args.ucl_half_life,
        },
        "ratings": {str(team_id): rating for team_id, rating in ratings.ratings.items()},
    }
    path = save_json("european_strength", "ucl_2026", payload)

    print(f"\nEuropean Elo matches: {len(ordered)}")
    print(f"UCL baseline: H {ucl_home:.3f} | A {ucl_away:.3f} | n={len(ucl_rows)}")
    print("\nToday's clubs:")
    for team_id, team_name in sorted(TEAMS.items(), key=lambda x: x[1]):
        print(f"  {team_name:20s} {ratings.get(team_id):.1f}")

    print(f"\nSaved European strength to {path}")


if __name__ == "__main__":
    main()

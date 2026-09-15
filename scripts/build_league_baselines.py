from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import DOMESTIC_LEAGUES, MATCH_DATE
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from model.ewma import ewma

COMPLETED = {"FT", "AET", "PEN"}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cached_league_fixtures(
    client: APIFootballClient,
    league_id: int,
    season: int,
) -> list[dict[str, Any]]:
    key = f"league_{league_id}_season_{season}"
    cached = load_json("league_fixture_lists", key)
    if cached is not None:
        return cached
    rows = client.fixtures(league=league_id, season=season).response
    save_json("league_fixture_lists", key, rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build recency-weighted domestic goal baselines for UCL clubs."
    )
    parser.add_argument(
        "--seasons", type=int, nargs="+", default=[2026, 2025, 2024, 2023]
    )
    parser.add_argument("--cutoff", default=MATCH_DATE)
    parser.add_argument("--window", type=int, default=300)
    parser.add_argument("--half-life", type=float, default=180.0)
    args = parser.parse_args()

    cutoff = datetime.fromisoformat(args.cutoff + "T00:00:00+00:00")
    client = APIFootballClient()

    unique = {
        row["league_id"]: row
        for row in DOMESTIC_LEAGUES.values()
    }
    output: dict[str, Any] = {
        "meta": {
            "cutoff": args.cutoff,
            "seasons": args.seasons,
            "window": args.window,
            "half_life": args.half_life,
        },
        "leagues": {},
    }

    for league_id, info in sorted(unique.items(), key=lambda x: x[1]["league_name"]):
        fixtures: list[dict[str, Any]] = []
        for season in args.seasons:
            rows = cached_league_fixtures(client, league_id, season)
            fixtures.extend(
                row for row in rows
                if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
                and parse_dt(row["fixture"]["date"]) < cutoff
                and row.get("goals", {}).get("home") is not None
                and row.get("goals", {}).get("away") is not None
            )

        # De-duplicate in case provider season boundaries overlap.
        dedup = {
            int(row["fixture"]["id"]): row
            for row in fixtures
        }
        ordered = sorted(dedup.values(), key=lambda row: parse_dt(row["fixture"]["date"]))
        if args.window > 0:
            ordered = ordered[-args.window:]

        home_goals = [float(row["goals"]["home"]) for row in ordered]
        away_goals = [float(row["goals"]["away"]) for row in ordered]
        home_rate = ewma(home_goals, args.half_life)
        away_rate = ewma(away_goals, args.half_life)

        output["leagues"][str(league_id)] = {
            **info,
            "n": len(ordered),
            "home_goals": home_rate,
            "away_goals": away_rate,
            "simple_home_goals": (sum(home_goals) / len(home_goals)) if home_goals else None,
            "simple_away_goals": (sum(away_goals) / len(away_goals)) if away_goals else None,
        }

        print(
            f"{info['league_name']:20s} ({league_id}) | n={len(ordered):3d} | "
            f"H {home_rate:.3f} | A {away_rate:.3f}"
        )

    path = save_json("league_goal_baselines", "ucl_2026", output)
    print(f"\nSaved league baselines to {path}")


if __name__ == "__main__":
    main()

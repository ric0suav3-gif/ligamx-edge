from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import DOMESTIC_LEAGUES, MATCH_DATE, UCL_LEAGUE_ID
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from ingest.statistics import parse_fixture_statistics
from model.dispersion import fit_count_distribution

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


def cached_fixture_list(
    client: APIFootballClient,
    league_id: int,
    season: int,
) -> list[dict[str, Any]]:
    key = f"league_{league_id}_season_{season}"
    cached = load_json("stat_fixture_lists", key)
    if cached is not None:
        return cached
    rows = client.fixtures(league=league_id, season=season).response
    save_json("stat_fixture_lists", key, rows)
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


def proper_ucl(row: dict[str, Any]) -> bool:
    round_name = str(row.get("league", {}).get("round") or "").lower()
    excluded = ("qualif", "prelim", "play-off", "playoff")
    return not any(token in round_name for token in excluded)


def collect_recent(
    client: APIFootballClient,
    league_id: int,
    seasons: list[int],
    cutoff: datetime,
    window: int,
    proper_stage_only: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season in seasons:
        rows.extend(cached_fixture_list(client, league_id, season))

    dedup = {
        int(row["fixture"]["id"]): row
        for row in rows
        if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
        and parse_dt(row["fixture"]["date"]) < cutoff
        and (not proper_stage_only or proper_ucl(row))
    }
    ordered = sorted(dedup.values(), key=lambda row: parse_dt(row["fixture"]["date"]))
    return ordered[-window:] if window > 0 else ordered


def summarize_environment(
    client: APIFootballClient,
    fixtures: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    home_values = {stat: [] for stat in STATS}
    away_values = {stat: [] for stat in STATS}
    complete_pairs = {stat: 0 for stat in STATS}

    for idx, fixture in enumerate(fixtures, start=1):
        fixture_id = int(fixture["fixture"]["id"])
        parsed = parse_fixture_statistics(cached_stats(client, fixture_id))
        home_id = int(fixture["teams"]["home"]["id"])
        away_id = int(fixture["teams"]["away"]["id"])
        h = parsed.get(home_id, {})
        a = parsed.get(away_id, {})

        for stat in STATS:
            hv = h.get(stat)
            av = a.get(stat)
            if hv is not None:
                home_values[stat].append(float(hv))
            if av is not None:
                away_values[stat].append(float(av))
            if hv is not None and av is not None:
                complete_pairs[stat] += 1

        if idx % 25 == 0 or idx == len(fixtures):
            print(f"  {label}: stats {idx}/{len(fixtures)}")

    out: dict[str, Any] = {"n_fixtures": len(fixtures), "stats": {}}
    for stat in STATS:
        hfit = fit_count_distribution(home_values[stat])
        afit = fit_count_distribution(away_values[stat])
        combined = fit_count_distribution(home_values[stat] + away_values[stat])
        out["stats"][stat] = {
            "home": hfit.__dict__,
            "away": afit.__dict__,
            "combined": combined.__dict__,
            "complete_pairs": complete_pairs[stat],
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build domestic and proper-stage UCL count-stat baselines."
    )
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=[2026, 2025, 2024],
    )
    parser.add_argument("--cutoff", default=MATCH_DATE)
    parser.add_argument("--league-window", type=int, default=100)
    parser.add_argument("--ucl-window", type=int, default=200)
    args = parser.parse_args()

    cutoff = datetime.fromisoformat(args.cutoff + "T00:00:00+00:00")
    client = APIFootballClient()
    unique_leagues = {
        info["league_id"]: info
        for info in DOMESTIC_LEAGUES.values()
    }

    payload: dict[str, Any] = {
        "meta": {
            "cutoff": args.cutoff,
            "seasons": args.seasons,
            "league_window": args.league_window,
            "ucl_window": args.ucl_window,
        },
        "domestic": {},
        "ucl": {},
    }

    print("Building domestic stat environments...")
    for league_id, info in sorted(unique_leagues.items(), key=lambda x: x[1]["league_name"]):
        fixtures = collect_recent(
            client,
            league_id=league_id,
            seasons=args.seasons,
            cutoff=cutoff,
            window=args.league_window,
        )
        label = f"{info['league_name']} ({league_id})"
        env = summarize_environment(client, fixtures, label)
        env["league_id"] = league_id
        env["league_name"] = info["league_name"]
        env["country"] = info["country"]
        payload["domestic"][str(league_id)] = env

        shots = env["stats"]["shots"]
        sot = env["stats"]["shots_on_target"]
        corners = env["stats"]["corners"]
        print(
            f"{label:28s} | "
            f"Shots H {shots['home']['mean']:.2f} A {shots['away']['mean']:.2f} | "
            f"SOT H {sot['home']['mean']:.2f} A {sot['away']['mean']:.2f} | "
            f"Corners H {corners['home']['mean']:.2f} A {corners['away']['mean']:.2f}"
        )

    print("\nBuilding proper-stage UCL stat environment...")
    ucl_fixtures = collect_recent(
        client,
        league_id=UCL_LEAGUE_ID,
        seasons=args.seasons,
        cutoff=cutoff,
        window=args.ucl_window,
        proper_stage_only=True,
    )
    payload["ucl"] = summarize_environment(client, ucl_fixtures, "UCL proper stage")
    payload["ucl"]["league_id"] = UCL_LEAGUE_ID

    path = save_json("stat_baselines", "ucl_2026", payload)
    print(f"\nSaved stat baselines to {path}")

    for stat in ("shots", "shots_on_target", "corners"):
        row = payload["ucl"]["stats"][stat]
        print(
            f"UCL {stat:16s} | "
            f"H {row['home']['mean']:.2f} | "
            f"A {row['away']['mean']:.2f} | "
            f"r {row['combined']['r'] if row['combined']['r'] is not None else 'Poisson'}"
        )


if __name__ == "__main__":
    main()

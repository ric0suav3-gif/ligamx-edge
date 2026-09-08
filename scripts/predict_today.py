from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import DOMESTIC_LEAGUES, FIXTURES, MATCH_DATE
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from ingest.odds import fixture_1x2
from model.ucl import DomesticGoalProfile, project_goals


def required(kind: str, key: str) -> Any:
    value = load_json(kind, key)
    if value is None:
        raise SystemExit(
            f"Missing {kind}/{key}. Run the prerequisite build script first."
        )
    return value


def fmt_pct(p: float) -> str:
    return f"{100.0 * p:5.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate first UCL Edge v0 goal/1X2 projections."
    )
    parser.add_argument("--shrinkage", type=float, default=0.65)
    parser.add_argument("--no-odds", action="store_true")
    args = parser.parse_args()

    profiles = required("team_profiles", "ucl_2026")
    baselines = required("league_goal_baselines", "ucl_2026")
    europe = required("european_strength", "ucl_2026")
    ratings = europe["ratings"]
    ucl_base = europe["ucl_baseline"]

    client = None if args.no_odds else APIFootballClient()
    output: dict[str, Any] = {
        "date": MATCH_DATE,
        "version": "ucl-edge-v0",
        "shrinkage": args.shrinkage,
        "fixtures": {},
    }

    print(f"UCL EDGE v0 — {MATCH_DATE}")
    print("Goals + 1X2 only. This is an uncalibrated first-pass model.\n")

    for fixture_id, fixture in FIXTURES.items():
        home_id = int(fixture["home"]["id"])
        away_id = int(fixture["away"]["id"])
        home_name = fixture["home"]["name"]
        away_name = fixture["away"]["name"]

        home_profile = profiles["teams"][str(home_id)]
        away_profile = profiles["teams"][str(away_id)]
        home_league_id = int(DOMESTIC_LEAGUES[home_id]["league_id"])
        away_league_id = int(DOMESTIC_LEAGUES[away_id]["league_id"])
        home_base = baselines["leagues"][str(home_league_id)]
        away_base = baselines["leagues"][str(away_league_id)]

        home = DomesticGoalProfile(
            team_id=home_id,
            home_for=float(home_profile["home"]["goals"]["for"]),
            home_against=float(home_profile["home"]["goals"]["against"]),
            away_for=float(home_profile["away"]["goals"]["for"]),
            away_against=float(home_profile["away"]["goals"]["against"]),
            league_home_goals=float(home_base["home_goals"]),
            league_away_goals=float(home_base["away_goals"]),
            elo=float(ratings.get(str(home_id), 1500.0)),
        )
        away = DomesticGoalProfile(
            team_id=away_id,
            home_for=float(away_profile["home"]["goals"]["for"]),
            home_against=float(away_profile["home"]["goals"]["against"]),
            away_for=float(away_profile["away"]["goals"]["for"]),
            away_against=float(away_profile["away"]["goals"]["against"]),
            league_home_goals=float(away_base["home_goals"]),
            league_away_goals=float(away_base["away_goals"]),
            elo=float(ratings.get(str(away_id), 1500.0)),
        )

        projection = project_goals(
            home=home,
            away=away,
            ucl_home_baseline=float(ucl_base["home_goals"]),
            ucl_away_baseline=float(ucl_base["away_goals"]),
            shrinkage=args.shrinkage,
        )
        p = projection.one_x_two

        market = None if client is None else fixture_1x2(client, fixture_id)
        row: dict[str, Any] = {
            "fixture_id": fixture_id,
            "home": home_name,
            "away": away_name,
            "home_xg": projection.home_xg,
            "away_xg": projection.away_xg,
            "elo_home": home.elo,
            "elo_away": away.elo,
            "probabilities": {
                "home": p.home,
                "draw": p.draw,
                "away": p.away,
            },
            "fair_odds": {
                "home": p.fair_home,
                "draw": p.fair_draw,
                "away": p.fair_away,
            },
        }

        print("=" * 72)
        print(f"{home_name} vs {away_name}  | fixture {fixture_id}")
        print(
            f"Elo {home.elo:.0f} - {away.elo:.0f} | "
            f"xG {projection.home_xg:.2f} - {projection.away_xg:.2f}"
        )
        print(
            f"MODEL  H {fmt_pct(p.home)} ({p.fair_home:.2f}) | "
            f"D {fmt_pct(p.draw)} ({p.fair_draw:.2f}) | "
            f"A {fmt_pct(p.away)} ({p.fair_away:.2f})"
        )

        if market:
            market_row: dict[str, Any] = {"best": {}, "median": market.median_odds}
            probs = {"home": p.home, "draw": p.draw, "away": p.away}
            edge_parts = []
            for outcome in ("home", "draw", "away"):
                price = market.best[outcome]
                edge = price.odd * probs[outcome] - 1.0
                market_row["best"][outcome] = {
                    "odd": price.odd,
                    "bookmaker": price.bookmaker,
                    "edge": edge,
                }
                edge_parts.append(
                    f"{outcome.upper()} {price.odd:.2f} {edge:+.1%}"
                )
            row["market"] = market_row
            print("BEST   " + " | ".join(edge_parts))

            ranked = sorted(
                (
                    (outcome, data["edge"], data["odd"], data["bookmaker"])
                    for outcome, data in market_row["best"].items()
                ),
                key=lambda x: x[1],
                reverse=True,
            )
            best_outcome, best_edge, best_odd, best_book = ranked[0]
            print(
                f"TOP EDGE: {best_outcome.upper()} {best_edge:+.1%} "
                f"@ {best_odd:.2f} ({best_book})"
            )
        else:
            print("MARKET: no 1X2 odds returned")

        output["fixtures"][str(fixture_id)] = row

    path = save_json("predictions", "ucl_2026_09_08", output)
    print("\n" + "=" * 72)
    print(f"Saved predictions to {path}")
    print(
        "IMPORTANT: v0 is for diagnostics. Do not treat its edges as validated "
        "until walk-forward backtesting and calibration are complete."
    )


if __name__ == "__main__":
    main()

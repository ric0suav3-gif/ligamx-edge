from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.league_strength_2026 import ASSOCIATION_COEFFICIENTS
from config.ucl_2026 import DOMESTIC_LEAGUES, FIXTURES, MATCH_DATE
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from ingest.odds import fixture_1x2, no_vig_probabilities
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
        description="Generate UCL Edge v0.1 goal/1X2 diagnostics."
    )
    parser.add_argument("--shrinkage", type=float, default=0.60)
    parser.add_argument("--split-prior", type=float, default=12.0)
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
        "version": "ucl-edge-v0.1",
        "shrinkage": args.shrinkage,
        "split_prior": args.split_prior,
        "fixtures": {},
    }

    print(f"UCL EDGE v0.1 — {MATCH_DATE}")
    print(
        "Goals + 1X2 diagnostic. Adds split-rate shrinkage, association-strength "
        "priors, and a proper-stage UCL scoring baseline.\n"
    )

    for fixture_id, fixture in FIXTURES.items():
        home_id = int(fixture["home"]["id"])
        away_id = int(fixture["away"]["id"])
        home_name = fixture["home"]["name"]
        away_name = fixture["away"]["name"]

        home_profile = profiles["teams"][str(home_id)]
        away_profile = profiles["teams"][str(away_id)]
        home_info = DOMESTIC_LEAGUES[home_id]
        away_info = DOMESTIC_LEAGUES[away_id]
        home_league_id = int(home_info["league_id"])
        away_league_id = int(away_info["league_id"])
        home_base = baselines["leagues"][str(home_league_id)]
        away_base = baselines["leagues"][str(away_league_id)]

        home_country = str(home_info["country"])
        away_country = str(away_info["country"])
        home_assoc = float(ASSOCIATION_COEFFICIENTS[home_country])
        away_assoc = float(ASSOCIATION_COEFFICIENTS[away_country])

        home = DomesticGoalProfile(
            team_id=home_id,
            home_for=float(home_profile["home"]["goals"]["for"]),
            home_against=float(home_profile["home"]["goals"]["against"]),
            away_for=float(home_profile["away"]["goals"]["for"]),
            away_against=float(home_profile["away"]["goals"]["against"]),
            league_home_goals=float(home_base["home_goals"]),
            league_away_goals=float(home_base["away_goals"]),
            home_n=int(home_profile["home"]["n"]),
            away_n=int(home_profile["away"]["n"]),
            association_coeff=home_assoc,
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
            home_n=int(away_profile["home"]["n"]),
            away_n=int(away_profile["away"]["n"]),
            association_coeff=away_assoc,
            elo=float(ratings.get(str(away_id), 1500.0)),
        )

        projection = project_goals(
            home=home,
            away=away,
            ucl_home_baseline=float(ucl_base["home_goals"]),
            ucl_away_baseline=float(ucl_base["away_goals"]),
            shrinkage=args.shrinkage,
            split_prior_matches=args.split_prior,
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
            "association_coeff_home": home_assoc,
            "association_coeff_away": away_assoc,
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

        print("=" * 78)
        print(f"{home_name} vs {away_name}  | fixture {fixture_id}")
        print(
            f"Elo {home.elo:.0f} - {away.elo:.0f} | "
            f"Assoc {home_assoc:.1f} - {away_assoc:.1f} | "
            f"xG {projection.home_xg:.2f} - {projection.away_xg:.2f}"
        )
        print(
            f"MODEL   H {fmt_pct(p.home)} ({p.fair_home:.2f}) | "
            f"D {fmt_pct(p.draw)} ({p.fair_draw:.2f}) | "
            f"A {fmt_pct(p.away)} ({p.fair_away:.2f})"
        )

        if market:
            probs = {"home": p.home, "draw": p.draw, "away": p.away}
            consensus = no_vig_probabilities(market.median_odds)
            median_edges = {
                outcome: market.median_odds[outcome] * probs[outcome] - 1.0
                for outcome in ("home", "draw", "away")
            }
            best_edges = {
                outcome: market.best[outcome].odd * probs[outcome] - 1.0
                for outcome in ("home", "draw", "away")
            }

            print(
                "MARKET  "
                + " | ".join(
                    f"{outcome.upper()} {fmt_pct(consensus[outcome])} "
                    f"(med {market.median_odds[outcome]:.2f})"
                    for outcome in ("home", "draw", "away")
                )
            )
            print(
                "EDGE-M  "
                + " | ".join(
                    f"{outcome.upper()} {median_edges[outcome]:+.1%}"
                    for outcome in ("home", "draw", "away")
                )
            )
            print(
                "BEST PX "
                + " | ".join(
                    f"{outcome.upper()} {market.best[outcome].odd:.2f} "
                    f"({market.best[outcome].bookmaker})"
                    for outcome in ("home", "draw", "away")
                )
            )

            ranked = sorted(
                median_edges.items(), key=lambda x: x[1], reverse=True
            )
            top_outcome, top_edge = ranked[0]
            divergence = abs(probs[top_outcome] - consensus[top_outcome])
            warning = " ⚠ LARGE MODEL/MARKET GAP" if divergence >= 0.12 else ""
            print(
                f"TOP DIAGNOSTIC EDGE: {top_outcome.upper()} "
                f"{top_edge:+.1%} on median market{warning}"
            )

            row["market"] = {
                "median_odds": market.median_odds,
                "no_vig_probabilities": consensus,
                "median_edges": median_edges,
                "best": {
                    outcome: {
                        "odd": market.best[outcome].odd,
                        "bookmaker": market.best[outcome].bookmaker,
                        "edge": best_edges[outcome],
                    }
                    for outcome in ("home", "draw", "away")
                },
            }
        else:
            print("MARKET: no 1X2 odds returned")

        output["fixtures"][str(fixture_id)] = row

    path = save_json("predictions", "ucl_2026_09_08_v01", output)
    print("\n" + "=" * 78)
    print(f"Saved predictions to {path}")
    print(
        "IMPORTANT: v0.1 is still a diagnostic model. Large model/market gaps are "
        "treated as evidence to investigate the model, not automatically as bets."
    )


if __name__ == "__main__":
    main()

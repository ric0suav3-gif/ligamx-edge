from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import DOMESTIC_LEAGUES, FIXTURES, MATCH_DATE
from ingest.cache import load_json, save_json
from model.stat_markets import asian_handicap, asian_team_total, h2h
from model.stat_projection import SplitStatProfile, TeamStatProfile, project_stat

PRIMARY_STATS = ("shots", "shots_on_target", "corners")


def required(kind: str, key: str) -> Any:
    value = load_json(kind, key)
    if value is None:
        raise SystemExit(
            f"Missing {kind}/{key}. Run the prerequisite build script first."
        )
    return value


def nearest_half(value: float) -> float:
    return round(value * 2.0) / 2.0


def team_total_lines(mean: float) -> list[float]:
    center = nearest_half(mean)
    lines = [center + delta for delta in (-2.0, -1.0, 0.0, 1.0, 2.0)]
    return sorted({max(0.5, line) for line in lines})


def handicap_lines(diff: float) -> list[float]:
    center = round((-diff) * 4.0) / 4.0
    return [center + delta for delta in (-1.0, -0.5, 0.0, 0.5, 1.0)]


def safe_float(value: Any, label: str) -> float:
    if value is None:
        raise ValueError(f"Missing required value: {label}")
    return float(value)


def build_team_profile(
    team_id: int,
    stat: str,
    profiles: dict[str, Any],
    baselines: dict[str, Any],
) -> TeamStatProfile:
    team = profiles["teams"][str(team_id)]
    league_id = int(DOMESTIC_LEAGUES[team_id]["league_id"])
    env = baselines["domestic"][str(league_id)]["stats"][stat]

    return TeamStatProfile(
        team_id=team_id,
        home=SplitStatProfile(
            for_rate=safe_float(team["home"][stat]["for"], f"{team_id} home {stat} for"),
            against_rate=safe_float(team["home"][stat]["against"], f"{team_id} home {stat} against"),
            n=int(team["home"]["n"]),
        ),
        away=SplitStatProfile(
            for_rate=safe_float(team["away"][stat]["for"], f"{team_id} away {stat} for"),
            against_rate=safe_float(team["away"][stat]["against"], f"{team_id} away {stat} against"),
            n=int(team["away"]["n"]),
        ),
        league_home_mean=safe_float(env["home"]["mean"], f"{league_id} {stat} home mean"),
        league_away_mean=safe_float(env["away"]["mean"], f"{league_id} {stat} away mean"),
    )


def fmt_fair(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Price first UCL Edge stat markets for Shots/SOT/Corners."
    )
    parser.add_argument("--split-prior", type=float, default=12.0)
    parser.add_argument("--matchup-shrinkage", type=float, default=0.55)
    args = parser.parse_args()

    profiles = required("team_profiles", "ucl_2026")
    baselines = required("stat_baselines", "ucl_2026")

    output: dict[str, Any] = {
        "date": MATCH_DATE,
        "version": "ucl-stat-edge-v0.1",
        "split_prior": args.split_prior,
        "matchup_shrinkage": args.matchup_shrinkage,
        "fixtures": {},
    }

    print(f"UCL STAT EDGE v0.1 — {MATCH_DATE}")
    print(
        "Primary markets: Shots, Shots on Target, Corners. "
        "No moneyline ranking. Cross-league stat transfer is intentionally neutral "
        "until it is learned from European stat history.\n"
    )

    for fixture_id, fixture in FIXTURES.items():
        home_id = int(fixture["home"]["id"])
        away_id = int(fixture["away"]["id"])
        home_name = fixture["home"]["name"]
        away_name = fixture["away"]["name"]

        print("=" * 90)
        print(f"{home_name} vs {away_name} | fixture {fixture_id}")
        fixture_out: dict[str, Any] = {
            "home": home_name,
            "away": away_name,
            "stats": {},
        }

        for stat in PRIMARY_STATS:
            ucl_env = baselines["ucl"]["stats"][stat]
            home = build_team_profile(home_id, stat, profiles, baselines)
            away = build_team_profile(away_id, stat, profiles, baselines)
            projection = project_stat(
                home=home,
                away=away,
                ucl_home_mean=safe_float(ucl_env["home"]["mean"], f"UCL {stat} home"),
                ucl_away_mean=safe_float(ucl_env["away"]["mean"], f"UCL {stat} away"),
                split_prior_matches=args.split_prior,
                matchup_shrinkage=args.matchup_shrinkage,
            )

            r = ucl_env["combined"].get("r")
            dispersion_r = None if r is None else float(r)
            h2h_market = h2h(
                projection.home_mean,
                projection.away_mean,
                dispersion_r,
                dispersion_r,
            )

            print(
                f"\n{stat.upper():16s} exp {home_name} {projection.home_mean:.2f} "
                f"| {away_name} {projection.away_mean:.2f}"
            )
            print(
                f"  H2H fair: {home_name} {fmt_fair(h2h_market.fair_first)} "
                f"| tie {h2h_market.tie:.1%} | "
                f"{away_name} {fmt_fair(h2h_market.fair_second)}"
            )

            home_totals = {}
            for line in team_total_lines(projection.home_mean):
                over = asian_team_total(
                    projection.home_mean, line, "over", dispersion_r
                )
                under = asian_team_total(
                    projection.home_mean, line, "under", dispersion_r
                )
                home_totals[str(line)] = {
                    "over_fair": over.fair_odds,
                    "under_fair": under.fair_odds,
                    "push": over.push,
                }
            away_totals = {}
            for line in team_total_lines(projection.away_mean):
                over = asian_team_total(
                    projection.away_mean, line, "over", dispersion_r
                )
                under = asian_team_total(
                    projection.away_mean, line, "under", dispersion_r
                )
                away_totals[str(line)] = {
                    "over_fair": over.fair_odds,
                    "under_fair": under.fair_odds,
                    "push": over.push,
                }

            print(f"  {home_name} team totals:")
            for line, row in home_totals.items():
                print(
                    f"    {line:>4} | O {fmt_fair(row['over_fair'])} "
                    f"| U {fmt_fair(row['under_fair'])}"
                )
            print(f"  {away_name} team totals:")
            for line, row in away_totals.items():
                print(
                    f"    {line:>4} | O {fmt_fair(row['over_fair'])} "
                    f"| U {fmt_fair(row['under_fair'])}"
                )

            ah_rows = {}
            diff = projection.home_mean - projection.away_mean
            print("  Asian handicap (home side):")
            for line in handicap_lines(diff):
                market = asian_handicap(
                    projection.home_mean,
                    projection.away_mean,
                    line,
                    dispersion_r,
                    dispersion_r,
                )
                ah_rows[str(line)] = {
                    "fair": market.fair_odds,
                    "push": market.push,
                }
                sign = "+" if line > 0 else ""
                print(
                    f"    {home_name} {sign}{line:g} | fair {fmt_fair(market.fair_odds)}"
                )

            fixture_out["stats"][stat] = {
                "home_mean": projection.home_mean,
                "away_mean": projection.away_mean,
                "dispersion_r": dispersion_r,
                "h2h": {
                    "home_win": h2h_market.first_win,
                    "tie": h2h_market.tie,
                    "away_win": h2h_market.second_win,
                    "home_fair": h2h_market.fair_first,
                    "away_fair": h2h_market.fair_second,
                },
                "home_team_totals": home_totals,
                "away_team_totals": away_totals,
                "home_asian_handicap": ah_rows,
            }

        output["fixtures"][str(fixture_id)] = fixture_out

    path = save_json("predictions", "ucl_stat_2026_09_08_v01", output)
    print("\n" + "=" * 90)
    print(f"Saved stat-market diagnostics to {path}")
    print(
        "IMPORTANT: v0.1 prices are diagnostics, not validated bets. "
        "The next calibration step is learning stat-specific European transfer "
        "factors and backtesting fair prices."
    )


if __name__ == "__main__":
    main()

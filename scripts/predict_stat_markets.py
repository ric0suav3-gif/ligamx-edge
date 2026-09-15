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

PRIMARY_STATS = (
    "shots",
    "shots_on_target",
    "corners",
    "fouls",
    "offsides",
    "yellow",
)


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


def effective_n(split: dict[str, Any], stat: str) -> int:
    row = split[stat]
    n_for = int(row.get("n_for") or 0)
    n_against = int(row.get("n_against") or 0)
    return min(n_for, n_against)


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
            n=effective_n(team["home"], stat),
        ),
        away=SplitStatProfile(
            for_rate=safe_float(team["away"][stat]["for"], f"{team_id} away {stat} for"),
            against_rate=safe_float(team["away"][stat]["against"], f"{team_id} away {stat} against"),
            n=effective_n(team["away"], stat),
        ),
        league_home_mean=safe_float(env["home"]["mean"], f"{league_id} {stat} home mean"),
        league_away_mean=safe_float(env["away"]["mean"], f"{league_id} {stat} away mean"),
    )


def fmt_fair(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def transfer_reliability(
    transfers: dict[str, Any] | None,
    home_id: int,
    away_id: int,
    stat: str,
) -> dict[str, Any]:
    if not transfers:
        return {"level": "LOW", "reason": "no learned UCL transfer file"}

    clamp_bounds = transfers.get("meta", {}).get("clamp", [0.75, 1.25])
    low, high = float(clamp_bounds[0]), float(clamp_bounds[1])

    rows = []
    for team_id in (home_id, away_id):
        row = (
            transfers.get("teams", {})
            .get(str(team_id), {})
            .get("stats", {})
            .get(stat, {})
        )
        n = min(
            int(row.get("n_attack") or 0),
            int(row.get("n_concession") or 0),
        )
        factors = [
            float(row.get("attack_transfer", 1.0)),
            float(row.get("concession_transfer", 1.0)),
        ]
        clamped = any(
            abs(factor - low) <= 0.005 or abs(factor - high) <= 0.005
            for factor in factors
        )
        rows.append({"team_id": team_id, "n": n, "clamped": clamped})

    min_n = min(row["n"] for row in rows)
    any_clamped = any(row["clamped"] for row in rows)

    if min_n >= 15:
        level = "HIGH"
    elif min_n >= 8:
        level = "MEDIUM"
    else:
        level = "LOW"

    if any_clamped:
        level = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}[level]

    reasons = [f"min proper-stage UCL sample n={min_n}"]
    if any_clamped:
        reasons.append("one or more transfer factors hit the clamp")

    return {
        "level": level,
        "reason": "; ".join(reasons),
        "teams": rows,
    }


def transfer_pair(
    transfers: dict[str, Any] | None,
    home_id: int,
    away_id: int,
    stat: str,
) -> tuple[float, float, dict[str, Any]]:
    if not transfers:
        return 1.0, 1.0, {"source": "neutral"}

    home_row = (
        transfers.get("teams", {})
        .get(str(home_id), {})
        .get("stats", {})
        .get(stat, {})
    )
    away_row = (
        transfers.get("teams", {})
        .get(str(away_id), {})
        .get("stats", {})
        .get(stat, {})
    )

    h_attack = float(home_row.get("attack_transfer", 1.0))
    h_conc = float(home_row.get("concession_transfer", 1.0))
    a_attack = float(away_row.get("attack_transfer", 1.0))
    a_conc = float(away_row.get("concession_transfer", 1.0))

    home_transfer = math.sqrt(max(1e-9, h_attack * a_conc))
    away_transfer = math.sqrt(max(1e-9, a_attack * h_conc))

    return home_transfer, away_transfer, {
        "source": "proper-stage UCL team transfer",
        "home_attack": h_attack,
        "home_concession": h_conc,
        "away_attack": a_attack,
        "away_concession": a_conc,
    }


def unavailable_reason(
    home_id: int,
    away_id: int,
    stat: str,
    profiles: dict[str, Any],
    baselines: dict[str, Any],
) -> str | None:
    """Return why a stat cannot be modeled without inventing missing API data."""
    for team_id in (home_id, away_id):
        team = profiles.get("teams", {}).get(str(team_id))
        if not team:
            return f"team {team_id}: no domestic profile"

        league_id = int(DOMESTIC_LEAGUES[team_id]["league_id"])
        env = (
            baselines.get("domestic", {})
            .get(str(league_id), {})
            .get("stats", {})
            .get(stat, {})
        )
        if not env:
            return f"league {league_id}: no {stat} baseline"
        if env.get("home", {}).get("mean") is None or env.get("away", {}).get("mean") is None:
            return f"league {league_id}: API has no usable {stat} coverage"

        for venue in ("home", "away"):
            stat_row = team.get(venue, {}).get(stat, {})
            if stat_row.get("for") is None or stat_row.get("against") is None:
                return f"team {team_id}: API has no usable domestic {stat} profile"
            if effective_n(team[venue], stat) <= 0:
                return f"team {team_id}: zero populated domestic {stat} sample"

    ucl_env = baselines.get("ucl", {}).get("stats", {}).get(stat, {})
    if ucl_env.get("home", {}).get("mean") is None or ucl_env.get("away", {}).get("mean") is None:
        return f"UCL environment: no usable {stat} baseline"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Price UCL Edge stat markets for shots/SOT/corners/fouls/offsides/yellows."
    )
    parser.add_argument("--split-prior", type=float, default=12.0)
    parser.add_argument("--matchup-shrinkage", type=float, default=0.55)
    parser.add_argument(
        "--neutral-transfers",
        action="store_true",
        help="Ignore learned UCL transfer factors for diagnostics.",
    )
    args = parser.parse_args()

    profiles = required("team_profiles", "ucl_2026")
    baselines = required("stat_baselines", "ucl_2026")
    transfers = None if args.neutral_transfers else load_json("stat_transfers", "ucl_2026")

    version = "ucl-stat-edge-v0.2" if transfers else "ucl-stat-edge-v0.1"
    output: dict[str, Any] = {
        "date": MATCH_DATE,
        "version": version,
        "split_prior": args.split_prior,
        "matchup_shrinkage": args.matchup_shrinkage,
        "transfers_loaded": transfers is not None,
        "fixtures": {},
    }

    print(f"UCL STAT EDGE {version.split('-v')[-1]} — {MATCH_DATE}")
    print(
        "Stat markets: Shots, Shots on Target, Corners, Fouls, Offsides, Yellow Cards. No moneyline ranking. "
        + (
            "Using shrunk, stat-specific proper-stage UCL transfer factors.\n"
            if transfers
            else "Using neutral cross-league transfers; build stat_transfers for v0.2.\n"
        )
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
            "unavailable_stats": {},
        }

        for stat in PRIMARY_STATS:
            reason = unavailable_reason(
                home_id, away_id, stat, profiles, baselines
            )
            if reason:
                fixture_out["unavailable_stats"][stat] = reason
                print(f"\n{stat.upper():16s} SKIP | {reason}")
                continue

            try:
                ucl_env = baselines["ucl"]["stats"][stat]
                home = build_team_profile(home_id, stat, profiles, baselines)
                away = build_team_profile(away_id, stat, profiles, baselines)
                home_transfer, away_transfer, transfer_meta = transfer_pair(
                    transfers, home_id, away_id, stat
                )
                reliability = transfer_reliability(
                    transfers, home_id, away_id, stat
                )
                projection = project_stat(
                    home=home,
                    away=away,
                    ucl_home_mean=safe_float(ucl_env["home"]["mean"], f"UCL {stat} home"),
                    ucl_away_mean=safe_float(ucl_env["away"]["mean"], f"UCL {stat} away"),
                    split_prior_matches=args.split_prior,
                    matchup_shrinkage=args.matchup_shrinkage,
                    home_transfer=home_transfer,
                    away_transfer=away_transfer,
                )
            except (KeyError, TypeError, ValueError) as exc:
                reason = f"model inputs unavailable: {exc}"
                fixture_out["unavailable_stats"][stat] = reason
                print(f"\n{stat.upper():16s} SKIP | {reason}")
                continue

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
                f"| {away_name} {projection.away_mean:.2f} "
                f"| transfer {home_transfer:.3f}/{away_transfer:.3f}"
            )
            print(
                f"  TRANSFER RELIABILITY: {reliability['level']} "
                f"({reliability['reason']})"
            )
            print(
                f"  H2H fair: {home_name} {fmt_fair(h2h_market.fair_first)} "
                f"| tie {h2h_market.tie:.1%} | "
                f"{away_name} {fmt_fair(h2h_market.fair_second)}"
            )

            home_totals = {}
            for line in team_total_lines(projection.home_mean):
                over = asian_team_total(projection.home_mean, line, "over", dispersion_r)
                under = asian_team_total(projection.home_mean, line, "under", dispersion_r)
                home_totals[str(line)] = {
                    "over_fair": over.fair_odds,
                    "under_fair": under.fair_odds,
                    "push": over.push,
                }

            away_totals = {}
            for line in team_total_lines(projection.away_mean):
                over = asian_team_total(projection.away_mean, line, "over", dispersion_r)
                under = asian_team_total(projection.away_mean, line, "under", dispersion_r)
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
                "home_transfer": home_transfer,
                "away_transfer": away_transfer,
                "transfer_meta": transfer_meta,
                "transfer_reliability": reliability,
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

    date_key = MATCH_DATE.replace("-", "_")
    key = f"ucl_stat_{date_key}_v02" if transfers else f"ucl_stat_{date_key}_v01"
    path = save_json("predictions", key, output)
    print("\n" + "=" * 90)
    print(f"Saved stat-market diagnostics to {path}")
    print(
        "IMPORTANT: these are diagnostic fair prices, not validated bets. "
        "Team totals use univariate count distributions; H2H/AH currently assume "
        "independent team counts and still need covariance calibration. "
        "Markets with missing API coverage are skipped rather than imputed."
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import DOMESTIC_LEAGUES, TEAMS
from ingest.cache import load_json, save_json
from model.ewma import ewma

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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def weighted_rate(home_value: float, away_value: float, home_n: int, away_n: int) -> float:
    total_n = home_n + away_n
    if total_n <= 0:
        raise ValueError("No domestic split sample")
    return (home_value * home_n + away_value * away_n) / total_n


def shrunk_transfer(raw: float, n: int, prior: float, low: float, high: float) -> float:
    weight = n / (n + prior) if n > 0 else 0.0
    value = 1.0 + weight * (raw - 1.0)
    return clamp(value, low, high)


def neutral(reason: str) -> dict[str, Any]:
    return {
        "attack_transfer": 1.0,
        "concession_transfer": 1.0,
        "raw_attack_transfer": None,
        "raw_concession_transfer": None,
        "n_attack": 0,
        "n_concession": 0,
        "reason": reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate stat-specific domestic-to-UCL transfer factors."
    )
    parser.add_argument("--half-life", type=float, default=10.0)
    parser.add_argument("--prior", type=float, default=15.0)
    parser.add_argument("--low", type=float, default=0.75)
    parser.add_argument("--high", type=float, default=1.25)
    args = parser.parse_args()

    profiles = load_json("team_profiles", "ucl_2026")
    baselines = load_json("stat_baselines", "ucl_2026")
    if profiles is None or baselines is None:
        raise SystemExit(
            "Missing team_profiles or stat_baselines. Build those first."
        )

    ucl_env = baselines["ucl"]["stats"]
    payload: dict[str, Any] = {
        "meta": {
            "half_life": args.half_life,
            "prior_matches": args.prior,
            "clamp": [args.low, args.high],
            "method": "team-specific proper-stage UCL relative-index transfer",
        },
        "teams": {},
    }

    for team_id, team_name in sorted(TEAMS.items(), key=lambda x: x[1]):
        hist = load_json("ucl_team_history", str(team_id))
        team_profile = profiles["teams"].get(str(team_id))
        if not team_profile:
            continue

        league_id = int(DOMESTIC_LEAGUES[team_id]["league_id"])
        domestic_env = baselines["domestic"][str(league_id)]["stats"]
        rows = [] if not hist else hist.get("matches", [])

        team_out: dict[str, Any] = {
            "team_id": team_id,
            "team_name": team_name,
            "ucl_matches": len(rows),
            "stats": {},
        }

        for stat in STATS:
            home_stat = team_profile["home"][stat]
            away_stat = team_profile["away"][stat]

            h_for_n = int(home_stat.get("n_for") or 0)
            a_for_n = int(away_stat.get("n_for") or 0)
            h_against_n = int(home_stat.get("n_against") or 0)
            a_against_n = int(away_stat.get("n_against") or 0)

            h_for = home_stat.get("for")
            a_for = away_stat.get("for")
            h_against = home_stat.get("against")
            a_against = away_stat.get("against")

            if None in (h_for, a_for, h_against, a_against):
                team_out["stats"][stat] = neutral("missing domestic profile")
                continue

            if min(
                h_for_n + a_for_n,
                h_against_n + a_against_n,
            ) <= 0:
                team_out["stats"][stat] = neutral("no populated domestic sample")
                continue

            d_home_mean = domestic_env[stat]["home"]["mean"]
            d_away_mean = domestic_env[stat]["away"]["mean"]
            u_home_mean = ucl_env[stat]["home"]["mean"]
            u_away_mean = ucl_env[stat]["away"]["mean"]

            if None in (d_home_mean, d_away_mean, u_home_mean, u_away_mean):
                team_out["stats"][stat] = neutral("missing environment baseline")
                continue

            domestic_for = weighted_rate(
                float(h_for), float(a_for), h_for_n, a_for_n
            )
            domestic_for_base = weighted_rate(
                float(d_home_mean), float(d_away_mean), h_for_n, a_for_n
            )
            domestic_against = weighted_rate(
                float(h_against), float(a_against), h_against_n, a_against_n
            )
            domestic_against_base = weighted_rate(
                float(d_away_mean), float(d_home_mean), h_against_n, a_against_n
            )

            if domestic_for_base <= 0 or domestic_against_base <= 0:
                team_out["stats"][stat] = neutral("non-positive domestic baseline")
                continue

            domestic_attack_index = domestic_for / domestic_for_base
            domestic_concession_index = domestic_against / domestic_against_base

            if domestic_attack_index <= 0 or domestic_concession_index <= 0:
                team_out["stats"][stat] = neutral("non-positive domestic index")
                continue

            euro_attack_indices: list[float | None] = []
            euro_concession_indices: list[float | None] = []
            for row in rows:
                own = row["stats_for"].get(stat)
                opp = row["stats_against"].get(stat)
                if row["venue"] == "home":
                    own_base = float(u_home_mean)
                    opp_base = float(u_away_mean)
                else:
                    own_base = float(u_away_mean)
                    opp_base = float(u_home_mean)

                euro_attack_indices.append(
                    None if own is None else float(own) / own_base
                )
                euro_concession_indices.append(
                    None if opp is None else float(opp) / opp_base
                )

            euro_attack_index = ewma(euro_attack_indices, args.half_life)
            euro_concession_index = ewma(euro_concession_indices, args.half_life)
            n_attack = sum(v is not None for v in euro_attack_indices)
            n_concession = sum(v is not None for v in euro_concession_indices)
            n = min(n_attack, n_concession)

            if euro_attack_index is None or euro_concession_index is None or n == 0:
                row_out = neutral("no proper-stage UCL stat sample")
                row_out["n_attack"] = n_attack
                row_out["n_concession"] = n_concession
                team_out["stats"][stat] = row_out
                continue

            raw_attack = euro_attack_index / domestic_attack_index
            raw_concession = euro_concession_index / domestic_concession_index
            attack_transfer = shrunk_transfer(
                raw_attack, n_attack, args.prior, args.low, args.high
            )
            concession_transfer = shrunk_transfer(
                raw_concession, n_concession, args.prior, args.low, args.high
            )

            team_out["stats"][stat] = {
                "attack_transfer": attack_transfer,
                "concession_transfer": concession_transfer,
                "raw_attack_transfer": raw_attack,
                "raw_concession_transfer": raw_concession,
                "n_attack": n_attack,
                "n_concession": n_concession,
                "domestic_attack_index": domestic_attack_index,
                "domestic_concession_index": domestic_concession_index,
            }

        payload["teams"][str(team_id)] = team_out
        print(f"{team_name:20s} | proper UCL n={len(rows)}")
        for stat in ("shots", "shots_on_target", "corners"):
            row = team_out["stats"][stat]
            print(
                f"  {stat:16s} atk x{row['attack_transfer']:.3f} "
                f"| conc x{row['concession_transfer']:.3f} "
                f"| n={min(row.get('n_attack', 0), row.get('n_concession', 0))}"
            )

    path = save_json("stat_transfers", "ucl_2026", payload)
    print(f"\nSaved stat-specific transfers to {path}")


if __name__ == "__main__":
    main()

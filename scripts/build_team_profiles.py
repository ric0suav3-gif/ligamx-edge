from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import TEAMS
from ingest.cache import load_json, save_json
from model.ewma import ewma

MODEL_STATS = (
    "goals",
    "shots",
    "shots_on_target",
    "corners",
    "fouls",
    "yellow",
    "red",
    "offsides",
    "cards",
)


def series(
    rows: list[dict[str, Any]],
    venue: str,
    stat: str,
    side: str,
) -> list[float | None]:
    out: list[float | None] = []
    for row in rows:
        if row["venue"] != venue:
            continue
        if stat == "goals":
            out.append(row[f"goals_{side}"])
        else:
            out.append(row[f"stats_{side}"].get(stat))
    return out


def split_profile(
    rows: list[dict[str, Any]],
    venue: str,
    half_life: float,
) -> dict[str, Any]:
    split_rows = [row for row in rows if row["venue"] == venue]
    result: dict[str, Any] = {"n": len(split_rows)}

    for stat in MODEL_STATS:
        for side in ("for", "against"):
            values = series(rows, venue, stat, side)
            result.setdefault(stat, {})[side] = ewma(values, half_life=half_life)
            result[stat][f"n_{side}"] = sum(v is not None for v in values)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build EWMA home/away team profiles from cached domestic history."
    )
    parser.add_argument("--half-life", type=float, default=25.0)
    args = parser.parse_args()

    profiles: dict[str, Any] = {
        "meta": {"half_life": args.half_life, "source": "domestic_history"},
        "teams": {},
    }

    for team_id, team_name in sorted(TEAMS.items(), key=lambda x: x[1]):
        payload = load_json("domestic_history", str(team_id))
        if not payload:
            print(
                f"Missing domestic history for {team_name} ({team_id}). "
                "Run scripts/backfill_domestic_history.py first."
            )
            continue

        rows = payload.get("matches", [])
        profile = {
            "team_id": team_id,
            "team_name": team_name,
            "domestic_league": payload.get("domestic_league"),
            "home": split_profile(rows, "home", args.half_life),
            "away": split_profile(rows, "away", args.half_life),
        }
        profiles["teams"][str(team_id)] = profile

        h = profile["home"]["goals"]
        a = profile["away"]["goals"]
        print(
            f"{team_name:20s} | "
            f"H GF {h['for'] if h['for'] is not None else float('nan'):.2f} "
            f"GA {h['against'] if h['against'] is not None else float('nan'):.2f} | "
            f"A GF {a['for'] if a['for'] is not None else float('nan'):.2f} "
            f"GA {a['against'] if a['against'] is not None else float('nan'):.2f}"
        )

    path = save_json("team_profiles", "ucl_2026", profiles)
    print(f"\nSaved profiles to {path}")


if __name__ == "__main__":
    main()

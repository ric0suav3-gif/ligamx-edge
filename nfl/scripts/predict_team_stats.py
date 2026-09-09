from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.cache import load_json, save_json
from nfl.model.team_stats import project_team_stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project NFL team statistical totals for one game."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument("--half-life", type=float, default=8.0)
    args = parser.parse_args()

    context = load_json("contexts", f"game_{args.game}")
    if context is None:
        raise SystemExit(
            "Missing context. Run backfill_game_context.py first."
        )

    histories = context.get("histories") or {}
    teams = context.get("teams") or {}
    if len(histories) != 2:
        raise SystemExit("Expected exactly two team histories.")

    projections = []
    for side in ("away", "home"):
        team = teams.get(side) or {}
        team_id = int(team["id"])
        own = histories.get(str(team_id))
        if own is None:
            raise SystemExit(f"Missing history for team {team_id}.")
        opp = next(
            hist for key, hist in histories.items()
            if int(key) != team_id
        )
        p = project_team_stats(
            team_id=team_id,
            team_name=str(team.get("name") or own.get("team_name") or team_id),
            own_matches=own.get("matches") or [],
            opponent_matches=opp.get("matches") or [],
            half_life=args.half_life,
        )
        if p is not None:
            projections.append((side, p))

    print(f"NFL EDGE TEAM STATS v0.1 | game {args.game}")
    print("Team totals are the primary model layer. Diagnostic until walk-forward calibrated.\n")

    for side, p in projections:
        print(f"{p.team_name} ({side.upper()}) | reliability {p.reliability}")
        print(f"  plays               {p.expected_plays:6.2f}")
        print(f"  pass attempts       {p.expected_pass_attempts:6.2f}")
        print(f"  completions         {p.expected_completions:6.2f}")
        print(f"  passing yards       {p.expected_passing_yards:6.2f}")
        print(f"  rush attempts       {p.expected_rush_attempts:6.2f}")
        print(f"  rushing yards       {p.expected_rushing_yards:6.2f}")
        print(f"  sacks made          {p.expected_sacks_made:6.2f}")
        print(f"  turnovers           {p.expected_turnovers:6.2f}")
        print(f"  points              {p.expected_points:6.2f}")
        print(f"  pass rate           {p.pass_rate:6.1%}")
        print(f"  completion rate     {p.completion_rate:6.1%}")
        print(f"  yards/pass attempt  {p.yards_per_pass_attempt:6.2f}")
        print(f"  yards/rush attempt  {p.yards_per_rush_attempt:6.2f}\n")

    if len(projections) == 2:
        a = projections[0][1]
        h = projections[1][1]
        print("MATCH TOTAL EXPECTATIONS")
        print(f"  plays               {a.expected_plays + h.expected_plays:6.2f}")
        print(f"  pass attempts       {a.expected_pass_attempts + h.expected_pass_attempts:6.2f}")
        print(f"  completions         {a.expected_completions + h.expected_completions:6.2f}")
        print(f"  passing yards       {a.expected_passing_yards + h.expected_passing_yards:6.2f}")
        print(f"  rush attempts       {a.expected_rush_attempts + h.expected_rush_attempts:6.2f}")
        print(f"  rushing yards       {a.expected_rushing_yards + h.expected_rushing_yards:6.2f}")
        print(f"  sacks               {a.expected_sacks_made + h.expected_sacks_made:6.2f}")
        print(f"  turnovers           {a.expected_turnovers + h.expected_turnovers:6.2f}")
        print(f"  points              {a.expected_points + h.expected_points:6.2f}")

    payload = {
        "game_id": str(args.game),
        "version": "nfl-edge-team-stats-v0.1",
        "half_life": args.half_life,
        "projections": [
            {"side": side, **p.to_dict()}
            for side, p in projections
        ],
    }
    path = save_json(
        "predictions",
        f"team_stats_game_{args.game}_v01",
        payload,
    )
    print(f"\nSaved team projections to {path}")


if __name__ == "__main__":
    main()

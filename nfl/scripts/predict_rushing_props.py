from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import load_json, save_json
from nfl.ingest.odds import best_player_prop_quotes, parse_player_prop_quotes
from nfl.model.distributions import count_fair_price, normal_fair_price
from nfl.model.rushing import project_player_rushing

RUSH_STATS = {"rush_attempts", "rushing_yards"}


def offered_ev(odd: float, win: float, push: float, loss: float) -> float:
    return win * (odd - 1.0) - loss


def find_player_team(
    player_name: str,
    histories: dict[str, Any],
) -> tuple[int, dict[str, Any]] | None:
    target = player_name.casefold().strip()
    matches = []
    for key, history in histories.items():
        for game in history.get("matches") or []:
            for player in game.get("players") or []:
                if str(player.get("player_name") or "").casefold().strip() == target:
                    matches.append((int(key), history))
                    break
            if matches and matches[-1][0] == int(key):
                break
    unique = {team_id: hist for team_id, hist in matches}
    if len(unique) != 1:
        return None
    return next(iter(unique.items()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostic v0.1 rushing-prop model for one NFL game."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument("--half-life", type=float, default=8.0)
    parser.add_argument("--min-ev", type=float, default=0.00)
    args = parser.parse_args()

    context = load_json("contexts", f"game_{args.game}")
    if context is None:
        raise SystemExit(
            "Missing game context. Run nfl/scripts/backfill_game_context.py first."
        )

    histories = context.get("histories") or {}
    if len(histories) != 2:
        raise SystemExit("Expected exactly two team histories in game context.")

    client = APINFLClient()
    raw_odds = client.odds(args.game).response
    quotes = [
        q for q in best_player_prop_quotes(parse_player_prop_quotes(raw_odds))
        if q.stat in RUSH_STATS
    ]

    rows = []
    projection_cache: dict[tuple[str, int], Any] = {}

    for quote in quotes:
        found = find_player_team(quote.player_name, histories)
        if found is None:
            rows.append(
                {
                    "player": quote.player_name,
                    "stat": quote.stat,
                    "side": quote.side,
                    "line": quote.line,
                    "book_odds": quote.odd,
                    "bookmaker": quote.bookmaker,
                    "status": "NO_TEAM_TENURE_HISTORY",
                }
            )
            continue

        team_id, own_history = found
        opp_history = next(
            hist for key, hist in histories.items()
            if int(key) != team_id
        )

        cache_key = (quote.player_name.casefold(), team_id)
        projection = projection_cache.get(cache_key)
        if projection is None:
            projection = project_player_rushing(
                player_name=quote.player_name,
                team_id=team_id,
                team_name=own_history.get("team_name") or str(team_id),
                own_matches=own_history.get("matches") or [],
                opp_matches=opp_history.get("matches") or [],
                half_life=args.half_life,
            )
            projection_cache[cache_key] = projection

        if projection is None:
            rows.append(
                {
                    "player": quote.player_name,
                    "stat": quote.stat,
                    "side": quote.side,
                    "line": quote.line,
                    "book_odds": quote.odd,
                    "bookmaker": quote.bookmaker,
                    "status": "INSUFFICIENT_HISTORY",
                }
            )
            continue

        if quote.stat == "rush_attempts":
            fair = count_fair_price(
                projection.expected_attempts,
                quote.line,
                quote.side,
                projection.attempts_r,
            )
            expected = projection.expected_attempts
        else:
            fair = normal_fair_price(
                projection.expected_rushing_yards,
                projection.rushing_yards_sd,
                quote.line,
                quote.side,
            )
            expected = projection.expected_rushing_yards

        ev = offered_ev(quote.odd, fair.win, fair.push, fair.loss)
        rows.append(
            {
                "player": quote.player_name,
                "team": projection.team_name,
                "stat": quote.stat,
                "side": quote.side,
                "line": quote.line,
                "book_odds": quote.odd,
                "bookmaker": quote.bookmaker,
                "model_fair": fair.fair_odds,
                "model_ev": ev,
                "expected": expected,
                "reliability": projection.reliability,
                "reason": projection.reason,
                "expected_team_rush_attempts": projection.expected_team_rush_attempts,
                "carry_share": projection.carry_share,
                "ypc": projection.yards_per_attempt,
                "yards_sd": projection.rushing_yards_sd,
                "status": "PRICED",
            }
        )

    priced = [row for row in rows if row.get("status") == "PRICED"]
    priced.sort(key=lambda row: row["model_ev"], reverse=True)

    print(f"NFL EDGE RUSHING v0.1 | game {args.game}")
    print("Diagnostic only: team-tenure history, single-book prices, not walk-forward calibrated.\n")

    shown = 0
    for row in priced:
        if row["model_ev"] < args.min_ev:
            continue
        shown += 1
        print(
            f"{shown:2d}. {row['player']} ({row['team']})\n"
            f"    {row['stat']} | {row['side'].upper()} {row['line']:g} @ "
            f"{row['book_odds']:.2f} ({row['bookmaker']})\n"
            f"    expected {row['expected']:.2f} | fair {row['model_fair']:.2f} | "
            f"model EV {row['model_ev']:+.1%} | reliability {row['reliability']}\n"
            f"    team rush {row['expected_team_rush_attempts']:.2f} | "
            f"share {row['carry_share']:.1%} | ypc {row['ypc']:.2f}\n"
        )

    unavailable = [row for row in rows if row.get("status") != "PRICED"]
    if unavailable:
        print("UNPRICED / NEED MORE HISTORY")
        for row in unavailable:
            print(
                f"  {row['player']:24s} | {row['stat']:18s} | "
                f"{row['status']}"
            )

    payload = {
        "game_id": str(args.game),
        "version": "nfl-edge-rushing-v0.1",
        "half_life": args.half_life,
        "rows": rows,
    }
    path = save_json("predictions", f"rushing_game_{args.game}_v01", payload)
    print(f"\nSaved predictions to {path}")


if __name__ == "__main__":
    main()

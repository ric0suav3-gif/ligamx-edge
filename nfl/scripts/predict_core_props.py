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
from nfl.model.passing import project_player_passing
from nfl.model.receiving import project_player_receiving
from nfl.model.rushing import project_player_rushing

SUPPORTED = {
    "rush_attempts",
    "rushing_yards",
    "passing_yards",
    "completions",
    "passing_touchdowns",
    "interceptions",
    "receiving_yards",
}


def offered_ev(odd: float, win: float, push: float, loss: float) -> float:
    return win * (odd - 1.0) - loss


def find_player_team(
    player_name: str,
    histories: dict[str, Any],
) -> tuple[int, dict[str, Any]] | None:
    target = player_name.casefold().strip()
    found: dict[int, dict[str, Any]] = {}
    for key, history in histories.items():
        for game in history.get("matches") or []:
            for player in game.get("players") or []:
                if str(player.get("player_name") or "").casefold().strip() == target:
                    found[int(key)] = history
                    break
            if int(key) in found:
                break
    if len(found) != 1:
        return None
    return next(iter(found.items()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NFL Edge core prop diagnostic model."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument("--half-life", type=float, default=8.0)
    parser.add_argument("--min-ev", type=float, default=0.0)
    args = parser.parse_args()

    context = load_json("contexts", f"game_{args.game}")
    if context is None:
        raise SystemExit(
            "Missing context. Run backfill_game_context.py first."
        )
    histories = context.get("histories") or {}
    if len(histories) != 2:
        raise SystemExit("Expected exactly two team histories.")

    client = APINFLClient()
    quotes = [
        q for q in best_player_prop_quotes(
            parse_player_prop_quotes(client.odds(args.game).response)
        )
        if q.stat in SUPPORTED
    ]

    projection_cache: dict[tuple[str, int, str], Any] = {}
    rows: list[dict[str, Any]] = []

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
        own_matches = own_history.get("matches") or []
        opp_matches = opp_history.get("matches") or []
        team_name = own_history.get("team_name") or str(team_id)

        if quote.stat in {"rush_attempts", "rushing_yards"}:
            kind = "rushing"
            cache_key = (quote.player_name.casefold(), team_id, kind)
            projection = projection_cache.get(cache_key)
            if projection is None:
                projection = project_player_rushing(
                    player_name=quote.player_name,
                    team_id=team_id,
                    team_name=team_name,
                    own_matches=own_matches,
                    opp_matches=opp_matches,
                    half_life=args.half_life,
                )
                projection_cache[cache_key] = projection
            if projection is None:
                status = "INSUFFICIENT_RUSHING_HISTORY"
                fair = None
                expected = None
            elif quote.stat == "rush_attempts":
                fair = count_fair_price(
                    projection.expected_attempts,
                    quote.line,
                    quote.side,
                    projection.attempts_r,
                )
                expected = projection.expected_attempts
                status = "PRICED"
            else:
                fair = normal_fair_price(
                    projection.expected_rushing_yards,
                    projection.rushing_yards_sd,
                    quote.line,
                    quote.side,
                )
                expected = projection.expected_rushing_yards
                status = "PRICED"

        elif quote.stat in {
            "passing_yards",
            "completions",
            "passing_touchdowns",
            "interceptions",
        }:
            kind = "passing"
            cache_key = (quote.player_name.casefold(), team_id, kind)
            projection = projection_cache.get(cache_key)
            if projection is None:
                projection = project_player_passing(
                    player_name=quote.player_name,
                    team_id=team_id,
                    team_name=team_name,
                    own_matches=own_matches,
                    opp_matches=opp_matches,
                    half_life=args.half_life,
                )
                projection_cache[cache_key] = projection
            if projection is None:
                status = "INSUFFICIENT_PASSING_HISTORY"
                fair = None
                expected = None
            elif quote.stat == "passing_yards":
                fair = normal_fair_price(
                    projection.expected_passing_yards,
                    projection.passing_yards_sd,
                    quote.line,
                    quote.side,
                )
                expected = projection.expected_passing_yards
                status = "PRICED"
            elif quote.stat == "completions":
                fair = normal_fair_price(
                    projection.expected_completions,
                    projection.completions_sd,
                    quote.line,
                    quote.side,
                )
                expected = projection.expected_completions
                status = "PRICED"
            elif quote.stat == "passing_touchdowns":
                fair = count_fair_price(
                    projection.expected_passing_touchdowns,
                    quote.line,
                    quote.side,
                    None,
                )
                expected = projection.expected_passing_touchdowns
                status = "PRICED"
            else:
                fair = count_fair_price(
                    projection.expected_interceptions,
                    quote.line,
                    quote.side,
                    None,
                )
                expected = projection.expected_interceptions
                status = "PRICED"

        else:
            kind = "receiving"
            cache_key = (quote.player_name.casefold(), team_id, kind)
            projection = projection_cache.get(cache_key)
            if projection is None:
                projection = project_player_receiving(
                    player_name=quote.player_name,
                    team_id=team_id,
                    team_name=team_name,
                    own_matches=own_matches,
                    opp_matches=opp_matches,
                    half_life=args.half_life,
                )
                projection_cache[cache_key] = projection
            if projection is None:
                status = "INSUFFICIENT_RECEIVING_HISTORY"
                fair = None
                expected = None
            else:
                fair = normal_fair_price(
                    projection.expected_receiving_yards,
                    projection.receiving_yards_sd,
                    quote.line,
                    quote.side,
                )
                expected = projection.expected_receiving_yards
                status = "PRICED"

        if status != "PRICED":
            rows.append(
                {
                    "player": quote.player_name,
                    "stat": quote.stat,
                    "side": quote.side,
                    "line": quote.line,
                    "book_odds": quote.odd,
                    "bookmaker": quote.bookmaker,
                    "status": status,
                }
            )
            continue

        ev = offered_ev(quote.odd, fair.win, fair.push, fair.loss)
        rows.append(
            {
                "player": quote.player_name,
                "team": team_name,
                "stat": quote.stat,
                "side": quote.side,
                "line": quote.line,
                "book_odds": quote.odd,
                "bookmaker": quote.bookmaker,
                "expected": expected,
                "model_fair": fair.fair_odds,
                "model_ev": ev,
                "reliability": projection.reliability,
                "reason": projection.reason,
                "status": "PRICED",
            }
        )

    priced = [row for row in rows if row.get("status") == "PRICED"]
    priced.sort(key=lambda row: row["model_ev"], reverse=True)

    print(f"NFL EDGE CORE PROPS v0.1 | game {args.game}")
    print(
        "Diagnostic only: team-tenure history, single-book prices, "
        "not walk-forward calibrated.\n"
    )

    rank = 0
    for row in priced:
        if row["model_ev"] < args.min_ev:
            continue
        rank += 1
        print(
            f"{rank:2d}. {row['player']} ({row['team']})\n"
            f"    {row['stat']} | {row['side'].upper()} {row['line']:g} "
            f"@ {row['book_odds']:.2f} ({row['bookmaker']})\n"
            f"    expected {row['expected']:.2f} | fair {row['model_fair']:.2f} | "
            f"model EV {row['model_ev']:+.1%} | reliability {row['reliability']}\n"
        )

    unavailable = [row for row in rows if row.get("status") != "PRICED"]
    if unavailable:
        print("UNPRICED / NEED MORE HISTORY")
        for row in unavailable:
            print(
                f"  {row['player']:24s} | {row['stat']:24s} | "
                f"{row['status']}"
            )

    path = save_json(
        "predictions",
        f"core_game_{args.game}_v01",
        {
            "game_id": str(args.game),
            "version": "nfl-edge-core-v0.1",
            "half_life": args.half_life,
            "rows": rows,
        },
    )
    print(f"\nSaved predictions to {path}")


if __name__ == "__main__":
    main()

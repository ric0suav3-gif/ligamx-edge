from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import load_json, save_json
from nfl.ingest.team_odds import TeamPropQuote, parse_team_prop_quotes
from nfl.model.distributions import count_fair_price, normal_fair_price
from nfl.model.team_stats import TeamStatProjection, project_team_stats


def offered_ev(odd: float, win: float, loss: float) -> float:
    return win * (odd - 1.0) - loss


def projection_for_side(
    context: dict[str, Any],
    side: str,
    half_life: float,
) -> TeamStatProjection:
    histories = context.get("histories") or {}
    team = (context.get("teams") or {}).get(side) or {}
    team_id = int(team["id"])
    own = histories[str(team_id)]
    opp = next(hist for key, hist in histories.items() if int(key) != team_id)
    p = project_team_stats(
        team_id=team_id,
        team_name=str(team.get("name") or own.get("team_name") or team_id),
        own_matches=own.get("matches") or [],
        opponent_matches=opp.get("matches") or [],
        half_life=half_life,
    )
    if p is None:
        raise RuntimeError(f"Could not project {side} team {team_id}")
    return p


def mean_sd(p: TeamStatProjection, stat: str) -> tuple[float, float]:
    mapping = {
        "points": (p.expected_points, p.points_sd),
        "pass_attempts": (p.expected_pass_attempts, p.pass_attempts_sd),
        "pass_completions": (p.expected_completions, p.completions_sd),
        "passing_yards": (p.expected_passing_yards, p.passing_yards_sd),
        "rush_attempts": (p.expected_rush_attempts, p.rush_attempts_sd),
        "rushing_yards": (p.expected_rushing_yards, p.rushing_yards_sd),
        "sacks": (p.expected_sacks_made, p.sacks_sd),
        "turnovers": (p.expected_turnovers, p.turnovers_sd),
    }
    if stat not in mapping:
        raise KeyError(stat)
    return mapping[stat]


def price_quote(
    quote: TeamPropQuote,
    home: TeamStatProjection,
    away: TeamStatProjection,
):
    if quote.scope == "home_total":
        mu, sd = mean_sd(home, quote.stat)
    elif quote.scope == "away_total":
        mu, sd = mean_sd(away, quote.stat)
    elif quote.scope == "match_total":
        home_mu, home_sd = mean_sd(home, quote.stat)
        away_mu, away_sd = mean_sd(away, quote.stat)
        mu = home_mu + away_mu
        # v0.1 independence assumption. We will replace this with empirical
        # covariance during walk-forward calibration.
        sd = math.sqrt(home_sd * home_sd + away_sd * away_sd)
    else:
        raise ValueError(f"Unsupported scope {quote.scope}")

    if quote.stat in {"sacks", "turnovers"}:
        fair = count_fair_price(mu, quote.line, quote.side, None)
    else:
        fair = normal_fair_price(mu, sd, quote.line, quote.side)
    return mu, sd, fair


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare NFL team-stat/point totals against bookmaker consensus."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument("--half-life", type=float, default=8.0)
    parser.add_argument("--min-books", type=int, default=2)
    parser.add_argument("--min-ev", type=float, default=0.0)
    args = parser.parse_args()

    context = load_json("contexts", f"game_{args.game}")
    if context is None:
        raise SystemExit("Missing context; run backfill_game_context.py first.")
    if int(context.get("schema_version") or 0) < 2:
        raise SystemExit("Stale context; rerun backfill_game_context.py.")

    home = projection_for_side(context, "home", args.half_life)
    away = projection_for_side(context, "away", args.half_life)

    client = APINFLClient()
    quotes = parse_team_prop_quotes(client.odds(args.game).response)

    groups: dict[tuple[str, str, str, float], list[TeamPropQuote]] = defaultdict(list)
    for q in quotes:
        groups[(q.stat, q.scope, q.side, q.line)].append(q)

    rows = []
    for (stat, scope, side, line), group in groups.items():
        books = {q.bookmaker for q in group}
        if len(books) < args.min_books:
            continue
        sample = group[0]
        try:
            mu, sd, fair = price_quote(sample, home, away)
        except KeyError:
            continue
        if fair.fair_odds is None:
            continue

        prices = [q.odd for q in group]
        median_odd = statistics.median(prices)
        best = max(group, key=lambda q: q.odd)
        ev = offered_ev(median_odd, fair.win, fair.loss)
        best_ev = offered_ev(best.odd, fair.win, fair.loss)

        rows.append(
            {
                "stat": stat,
                "scope": scope,
                "side": side,
                "line": line,
                "expected": mu,
                "sd": sd,
                "fair": fair.fair_odds,
                "books": len(books),
                "median_odd": median_odd,
                "best_odd": best.odd,
                "best_book": best.bookmaker,
                "consensus_ev": ev,
                "best_ev": best_ev,
            }
        )

    rows.sort(key=lambda r: r["consensus_ev"], reverse=True)

    print(f"NFL EDGE TEAM MARKETS v0.1 | game {args.game}")
    print(
        "Consensus comparator; team points/stats primary. "
        "Not walk-forward calibrated. Match totals assume independence.\n"
    )

    shown = 0
    for row in rows:
        if row["consensus_ev"] < args.min_ev:
            continue
        shown += 1
        print(
            f"{shown:2d}. {row['scope']:11s} | {row['stat']:18s} | "
            f"{row['side'].upper()} {row['line']:g}\n"
            f"    expected {row['expected']:.2f} | fair {row['fair']:.2f} | "
            f"median {row['median_odd']:.2f} ({row['books']} books) | "
            f"EV {row['consensus_ev']:+.1%}\n"
            f"    best {row['best_odd']:.2f} {row['best_book']} | "
            f"best EV {row['best_ev']:+.1%}\n"
        )

    if not rows:
        print("No mapped team markets with enough bookmaker support.")
    elif shown == 0:
        print("No team markets cleared the requested EV threshold.")

    path = save_json(
        "comparisons",
        f"team_game_{args.game}_v01",
        {
            "game_id": str(args.game),
            "version": "nfl-edge-team-market-v0.1",
            "min_books": args.min_books,
            "rows": rows,
        },
    )
    print(f"Saved comparison to {path}")


if __name__ == "__main__":
    main()

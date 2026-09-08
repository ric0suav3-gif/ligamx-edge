from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import FIXTURES, MATCH_DATE
from ingest.cache import load_json, save_json
from ingest.stat_odds import StatQuote, parse_stat_quotes
from model.stat_markets import asian_handicap, asian_match_total, asian_team_total, h2h

SAFE_MARKETS = {"home_total", "away_total"}
JOINT_MARKETS = {"match_total", "h2h", "handicap"}


def required(kind: str, key: str) -> Any:
    value = load_json(kind, key)
    if value is None:
        raise SystemExit(f"Missing {kind}/{key}. Run the prerequisite script first.")
    return value


def offered_ev(odd: float, win_equivalent: float, loss_equivalent: float) -> float:
    return win_equivalent * (odd - 1.0) - loss_equivalent


def price_quote(
    quote: StatQuote,
    home_mean: float,
    away_mean: float,
    r: float | None,
) -> tuple[float | None, float | None, str]:
    if quote.market_type == "match_total":
        market = asian_match_total(
            home_mean, away_mean, float(quote.line), quote.selection, r, r
        )
        return (
            market.fair_odds,
            offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent),
            "team-count independence",
        )

    if quote.market_type == "home_total":
        market = asian_team_total(home_mean, float(quote.line), quote.selection, r)
        return (
            market.fair_odds,
            offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent),
            "univariate",
        )

    if quote.market_type == "away_total":
        market = asian_team_total(away_mean, float(quote.line), quote.selection, r)
        return (
            market.fair_odds,
            offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent),
            "univariate",
        )

    if quote.market_type == "h2h":
        market = h2h(home_mean, away_mean, r, r)
        probs = {
            "home": market.first_win,
            "draw": market.tie,
            "away": market.second_win,
        }
        p = probs[quote.selection]
        fair = None if p <= 0 else 1.0 / p
        return fair, quote.odd * p - 1.0, "team-count independence"

    if quote.market_type == "handicap":
        if quote.selection == "home":
            market = asian_handicap(home_mean, away_mean, float(quote.line), r, r)
        else:
            market = asian_handicap(away_mean, home_mean, float(quote.line), r, r)
        return (
            market.fair_odds,
            offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent),
            "team-count independence",
        )

    return None, None, "unsupported"


def grouped_quotes(quotes: list[StatQuote]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, float | None], list[StatQuote]] = {}
    for quote in quotes:
        key = (quote.stat, quote.market_type, quote.selection, quote.line)
        grouped.setdefault(key, []).append(quote)

    out = []
    for key, items in grouped.items():
        unique_books = {q.bookmaker for q in items}
        prices = [q.odd for q in items]
        best = max(items, key=lambda q: q.odd)
        out.append(
            {
                "key": key,
                "template": best,
                "best": best,
                "best_odds": best.odd,
                "median_odds": statistics.median(prices),
                "books": len(unique_books),
                "bookmakers": sorted(unique_books),
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare UCL Stat Edge fair prices with bookmaker lines."
    )
    parser.add_argument("--min-edge", type=float, default=0.05)
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--min-books", type=int, default=2)
    parser.add_argument(
        "--include-low",
        action="store_true",
        help="Include LOW transfer-reliability markets.",
    )
    parser.add_argument(
        "--experimental-joint",
        action="store_true",
        help="Also include H2H, handicap and match-total markets. These are not safe-mode markets.",
    )
    args = parser.parse_args()

    predictions = required("predictions", "ucl_stat_2026_09_08_v02")
    ranked: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    allowed = set(SAFE_MARKETS)
    if args.experimental_joint:
        allowed |= JOINT_MARKETS

    for fixture_id, fixture in FIXTURES.items():
        pred = predictions["fixtures"].get(str(fixture_id))
        if pred is None:
            continue

        raw_odds = load_json("odds", f"fixture_{fixture_id}")
        if raw_odds is None:
            continue

        groups = grouped_quotes(parse_stat_quotes(raw_odds))
        for group in groups:
            quote = group["template"]
            if quote.market_type not in allowed:
                continue
            if group["books"] < args.min_books:
                continue

            stat_pred = pred["stats"].get(quote.stat)
            if stat_pred is None:
                continue

            home_mean = float(stat_pred["home_mean"])
            away_mean = float(stat_pred["away_mean"])
            r_value = stat_pred.get("dispersion_r")
            r = None if r_value is None else float(r_value)

            consensus_quote = replace(quote, odd=float(group["median_odds"]))
            fair, ev_consensus, structural_note = price_quote(
                consensus_quote, home_mean, away_mean, r
            )
            if fair is None or ev_consensus is None:
                continue

            best_quote = replace(quote, odd=float(group["best_odds"]))
            _, ev_best, _ = price_quote(best_quote, home_mean, away_mean, r)

            reliability = stat_pred.get("transfer_reliability", {})
            level = str(reliability.get("level") or "UNKNOWN")
            reason = str(reliability.get("reason") or "not recorded")

            row = {
                "fixture_id": fixture_id,
                "match": f"{fixture['home']['name']} vs {fixture['away']['name']}",
                "stat": quote.stat,
                "market_type": quote.market_type,
                "selection": quote.selection,
                "line": quote.line,
                "model_fair": fair,
                "median_book_odds": float(group["median_odds"]),
                "best_book_odds": float(group["best_odds"]),
                "best_bookmaker": group["best"].bookmaker,
                "book_count": group["books"],
                "model_ev_consensus": ev_consensus,
                "model_ev_best": ev_best,
                "home_mean": home_mean,
                "away_mean": away_mean,
                "transfer_reliability": level,
                "reliability_reason": reason,
                "structural_note": structural_note,
                "bet_id": quote.bet_id,
                "market_name": quote.market_name,
            }
            all_rows.append(row)

            eligible = level != "LOW" or args.include_low
            if eligible and ev_consensus >= args.min_edge:
                ranked.append(row)

    ranked.sort(key=lambda row: row["model_ev_consensus"], reverse=True)
    ranked = ranked[: args.top]

    mode = "SAFE TEAM-TOTAL MODE" if not args.experimental_joint else "EXPERIMENTAL JOINT MODE"
    print(f"UCL STAT EDGE — {mode} — {MATCH_DATE}")
    print(
        f"Using median market price across at least {args.min_books} bookmakers. "
        "Best price is shown only after consensus validation.\n"
    )

    if not ranked:
        print(f"No eligible quotes at or above {args.min_edge:.0%} consensus EV.")
    else:
        for idx, row in enumerate(ranked, start=1):
            qline = "" if row["line"] is None else f" {row['line']:g}"
            print(
                f"{idx:2d}. {row['match']}\n"
                f"    {row['stat']} | {row['market_type']} | "
                f"{row['selection'].upper()}{qline}\n"
                f"    model fair {row['model_fair']:.2f} | "
                f"median {row['median_book_odds']:.2f} ({row['book_count']} books) | "
                f"consensus EV {row['model_ev_consensus']:+.1%}\n"
                f"    best {row['best_book_odds']:.2f} ({row['best_bookmaker']}) | "
                f"best-price EV {row['model_ev_best']:+.1%}\n"
                f"    expected {row['home_mean']:.2f}-{row['away_mean']:.2f} | "
                f"reliability {row['transfer_reliability']} | {row['structural_note']}\n"
            )

    payload = {
        "date": MATCH_DATE,
        "version": "ucl-stat-book-compare-v0.2",
        "mode": mode,
        "min_books": args.min_books,
        "min_edge": args.min_edge,
        "ranked": ranked,
        "all_quotes": all_rows,
    }
    path = save_json("book_comparisons", "ucl_2026_09_08_v02_safe", payload)
    print(f"Saved comparison to {path}")


if __name__ == "__main__":
    main()

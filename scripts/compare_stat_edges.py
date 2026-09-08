from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import FIXTURES, MATCH_DATE
from ingest.cache import load_json, save_json
from ingest.stat_odds import StatQuote, best_stat_quotes, parse_stat_quotes
from model.stat_markets import asian_handicap, asian_match_total, asian_team_total, h2h


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
    """Return (fair_odds, expected_return, structural_note)."""
    if quote.market_type == "match_total":
        market = asian_match_total(
            home_mean, away_mean, float(quote.line), quote.selection, r, r
        )
        ev = offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent)
        return market.fair_odds, ev, "team-count independence"

    if quote.market_type == "home_total":
        market = asian_team_total(home_mean, float(quote.line), quote.selection, r)
        ev = offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent)
        return market.fair_odds, ev, "univariate"

    if quote.market_type == "away_total":
        market = asian_team_total(away_mean, float(quote.line), quote.selection, r)
        ev = offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent)
        return market.fair_odds, ev, "univariate"

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
        ev = offered_ev(quote.odd, market.win_equivalent, market.loss_equivalent)
        return market.fair_odds, ev, "team-count independence"

    return None, None, "unsupported"


def label_quote(q: StatQuote) -> str:
    stat = {
        "shots": "Shots",
        "shots_on_target": "SOT",
        "corners": "Corners",
    }[q.stat]
    market = q.market_type.replace("_", " ")
    line = "" if q.line is None else f" {q.line:g}"
    return f"{stat} | {market} | {q.selection.upper()}{line}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare UCL Stat Edge fair prices with API-Football bookmaker lines."
    )
    parser.add_argument("--min-edge", type=float, default=0.05)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument(
        "--include-low",
        action="store_true",
        help="Include LOW transfer-reliability markets in the ranked table.",
    )
    args = parser.parse_args()

    predictions = required("predictions", "ucl_stat_2026_09_08_v02")
    ranked: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    for fixture_id, fixture in FIXTURES.items():
        pred = predictions["fixtures"].get(str(fixture_id))
        if pred is None:
            continue

        raw_odds = load_json("odds", f"fixture_{fixture_id}")
        if raw_odds is None:
            print(
                f"No cached odds for {fixture['home']['name']} vs {fixture['away']['name']}; "
                "run scripts/audit_odds_markets.py first."
            )
            continue

        quotes = best_stat_quotes(parse_stat_quotes(raw_odds))
        for quote in quotes:
            stat_pred = pred["stats"].get(quote.stat)
            if stat_pred is None:
                continue

            home_mean = float(stat_pred["home_mean"])
            away_mean = float(stat_pred["away_mean"])
            r_value = stat_pred.get("dispersion_r")
            r = None if r_value is None else float(r_value)

            fair, ev, structural_note = price_quote(
                quote, home_mean, away_mean, r
            )
            if fair is None or ev is None:
                continue

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
                "book_odds": quote.odd,
                "bookmaker": quote.bookmaker,
                "model_fair": fair,
                "model_ev": ev,
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
            if eligible and ev >= args.min_edge:
                ranked.append(row)

    ranked.sort(key=lambda row: row["model_ev"], reverse=True)
    ranked = ranked[: args.top]

    print(f"UCL STAT EDGE — BOOK COMPARISON — {MATCH_DATE}")
    print(
        "Diagnostic only: positive EV is model-vs-book disagreement, not yet a "
        "validated betting edge. H2H/AH/match totals still use an independence approximation.\n"
    )

    if not ranked:
        print(
            f"No eligible quotes at or above {args.min_edge:.0%} model EV. "
            "Use --include-low to inspect low-reliability matches."
        )
    else:
        for idx, row in enumerate(ranked, start=1):
            qline = "" if row["line"] is None else f" {row['line']:g}"
            print(
                f"{idx:2d}. {row['match']}\n"
                f"    {row['stat']} | {row['market_type']} | "
                f"{row['selection'].upper()}{qline}\n"
                f"    model fair {row['model_fair']:.2f} | "
                f"book {row['book_odds']:.2f} ({row['bookmaker']}) | "
                f"model EV {row['model_ev']:+.1%}\n"
                f"    expected {row['home_mean']:.2f}-{row['away_mean']:.2f} | "
                f"transfer reliability {row['transfer_reliability']} | "
                f"{row['structural_note']}\n"
            )

    payload = {
        "date": MATCH_DATE,
        "version": "ucl-stat-book-compare-v0.1",
        "min_edge": args.min_edge,
        "ranked": ranked,
        "all_quotes": all_rows,
    }
    path = save_json("book_comparisons", "ucl_2026_09_08_v01", payload)
    print(f"Saved full comparison to {path}")


if __name__ == "__main__":
    main()

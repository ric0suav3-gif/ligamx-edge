from __future__ import annotations

import argparse
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import DOMESTIC_LEAGUES, FIXTURES, MATCH_DATE
from ingest.cache import load_json, save_json
from ingest.stat_odds import StatQuote, parse_stat_quotes
from model.stat_markets import asian_team_total
from model.stat_projection import SplitStatProfile, TeamStatProfile, project_stat
from scripts.predict_stat_markets import (
    PRIMARY_STATS,
    build_team_profile,
    safe_float,
    transfer_pair,
)


def required(kind: str, key: str) -> Any:
    value = load_json(kind, key)
    if value is None:
        raise SystemExit(f"Missing {kind}/{key}. Run the prerequisite script first.")
    return value


def offered_ev(odd: float, win_equivalent: float, loss_equivalent: float) -> float:
    return win_equivalent * (odd - 1.0) - loss_equivalent


def grouped_quotes(quotes: list[StatQuote]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, float | None], list[StatQuote]] = {}
    for quote in quotes:
        if quote.market_type not in {"home_total", "away_total"}:
            continue
        key = (quote.stat, quote.market_type, quote.selection, quote.line)
        grouped.setdefault(key, []).append(quote)

    out: list[dict[str, Any]] = []
    for key, items in grouped.items():
        unique_books = {q.bookmaker for q in items}
        prices = [float(q.odd) for q in items]
        best = max(items, key=lambda q: q.odd)
        out.append(
            {
                "key": key,
                "template": best,
                "best": best,
                "best_odds": float(best.odd),
                "median_odds": float(statistics.median(prices)),
                "books": len(unique_books),
                "bookmakers": sorted(unique_books),
            }
        )
    return out


def neutral_profile(team_id: int, ucl_home: float, ucl_away: float) -> TeamStatProfile:
    """Neutral opponent used only when API-Football has no usable domestic stat history.

    The neutral side contributes a relative factor of 1.0. This lets the covered
    team's own attack/concession profile drive its team-total projection without
    fabricating a missing opponent average.
    """
    return TeamStatProfile(
        team_id=team_id,
        home=SplitStatProfile(
            for_rate=ucl_home,
            against_rate=ucl_away,
            n=0,
        ),
        away=SplitStatProfile(
            for_rate=ucl_away,
            against_rate=ucl_home,
            n=0,
        ),
        league_home_mean=ucl_home,
        league_away_mean=ucl_away,
    )


def real_profile_or_none(
    team_id: int,
    stat: str,
    profiles: dict[str, Any],
    baselines: dict[str, Any],
) -> TeamStatProfile | None:
    try:
        return build_team_profile(team_id, stat, profiles, baselines)
    except (KeyError, TypeError, ValueError):
        return None


def projection_for_stat(
    home_id: int,
    away_id: int,
    stat: str,
    profiles: dict[str, Any],
    baselines: dict[str, Any],
    transfers: dict[str, Any] | None,
    split_prior: float,
    matchup_shrinkage: float,
) -> dict[str, Any] | None:
    ucl_env = baselines.get("ucl", {}).get("stats", {}).get(stat, {})
    try:
        ucl_home = safe_float(ucl_env.get("home", {}).get("mean"), f"UCL {stat} home")
        ucl_away = safe_float(ucl_env.get("away", {}).get("mean"), f"UCL {stat} away")
    except ValueError:
        return None

    home_real = real_profile_or_none(home_id, stat, profiles, baselines)
    away_real = real_profile_or_none(away_id, stat, profiles, baselines)
    if home_real is None and away_real is None:
        return None

    home = home_real or neutral_profile(home_id, ucl_home, ucl_away)
    away = away_real or neutral_profile(away_id, ucl_home, ucl_away)

    # Learned transfer factors are retained only when both sides have real inputs.
    if home_real is not None and away_real is not None:
        home_transfer, away_transfer, _ = transfer_pair(
            transfers, home_id, away_id, stat
        )
        reliability = "MODEL"
    else:
        home_transfer, away_transfer = 1.0, 1.0
        reliability = "ONE_SIDED_FALLBACK"

    projection = project_stat(
        home=home,
        away=away,
        ucl_home_mean=ucl_home,
        ucl_away_mean=ucl_away,
        split_prior_matches=split_prior,
        matchup_shrinkage=matchup_shrinkage,
        home_transfer=home_transfer,
        away_transfer=away_transfer,
    )

    r_value = ucl_env.get("combined", {}).get("r")
    dispersion_r = None if r_value is None else float(r_value)
    return {
        "home_mean": float(projection.home_mean),
        "away_mean": float(projection.away_mean),
        "dispersion_r": dispersion_r,
        "home_real": home_real is not None,
        "away_real": away_real is not None,
        "source": reliability,
    }


def price_team_total(
    quote: StatQuote,
    projection: dict[str, Any],
    odd: float,
) -> tuple[float, float] | None:
    if quote.line is None:
        return None
    if quote.market_type == "home_total":
        mean = projection["home_mean"]
        if not projection["home_real"]:
            return None
    elif quote.market_type == "away_total":
        mean = projection["away_mean"]
        if not projection["away_real"]:
            return None
    else:
        return None

    market = asian_team_total(
        mean,
        float(quote.line),
        quote.selection,
        projection["dispersion_r"],
    )
    if market.fair_odds is None:
        return None
    return (
        float(market.fair_odds),
        offered_ev(float(odd), market.win_equivalent, market.loss_equivalent),
    )


def quality_score(row: dict[str, Any]) -> float:
    """Rank within a fixture without pretending every candidate is equally reliable."""
    score = float(row["model_ev_consensus"])
    books = int(row["book_count"])
    reliability = str(row["transfer_reliability"])

    # Small ranking adjustments only; EV remains the dominant term.
    score += min(books, 5) * 0.003
    if reliability == "HIGH":
        score += 0.015
    elif reliability == "MEDIUM":
        score += 0.007
    elif reliability in {"LOW", "ONE_SIDED_FALLBACK"}:
        score -= 0.025
    return score


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Return the best available API-Football stat-market pick for every UCL match."
    )
    parser.add_argument("--min-books", type=int, default=2)
    parser.add_argument("--split-prior", type=float, default=12.0)
    parser.add_argument("--matchup-shrinkage", type=float, default=0.55)
    parser.add_argument("--top-per-match", type=int, default=5)
    args = parser.parse_args()

    date_key = MATCH_DATE.replace("-", "_")
    predictions = required("predictions", f"ucl_stat_{date_key}_v02")
    profiles = required("team_profiles", "ucl_2026")
    baselines = required("stat_baselines", "ucl_2026")
    transfers = load_json("stat_transfers", "ucl_2026")

    output: dict[str, Any] = {
        "date": MATCH_DATE,
        "version": "ucl-match-card-v0.1",
        "policy": "One ranked stat-market selection per fixture; no automatic PASS. Fallbacks are explicitly labeled.",
        "fixtures": {},
    }

    print(f"UCL EDGE — FULL MATCH CARD — {MATCH_DATE}")
    print("One best available stat-market selection per fixture. API-Football data only.\n")

    for fixture_id, fixture in FIXTURES.items():
        home_id = int(fixture["home"]["id"])
        away_id = int(fixture["away"]["id"])
        match = f"{fixture['home']['name']} vs {fixture['away']['name']}"
        raw_odds = load_json("odds", f"fixture_{fixture_id}")
        groups = grouped_quotes(parse_stat_quotes(raw_odds or []))
        pred_fixture = predictions.get("fixtures", {}).get(str(fixture_id), {})
        candidates: list[dict[str, Any]] = []

        for group in groups:
            quote = group["template"]
            if group["books"] < args.min_books:
                continue

            stat_pred = pred_fixture.get("stats", {}).get(quote.stat)
            source = "FULL_MODEL"
            if stat_pred is not None:
                projection = {
                    "home_mean": float(stat_pred["home_mean"]),
                    "away_mean": float(stat_pred["away_mean"]),
                    "dispersion_r": None if stat_pred.get("dispersion_r") is None else float(stat_pred["dispersion_r"]),
                    "home_real": True,
                    "away_real": True,
                }
                rel = stat_pred.get("transfer_reliability", {})
                reliability = str(rel.get("level") or "UNKNOWN")
            else:
                projection = projection_for_stat(
                    home_id,
                    away_id,
                    quote.stat,
                    profiles,
                    baselines,
                    transfers,
                    args.split_prior,
                    args.matchup_shrinkage,
                )
                if projection is None:
                    continue
                source = projection["source"]
                reliability = "LOW" if source == "ONE_SIDED_FALLBACK" else "UNKNOWN"

            consensus_quote = replace(quote, odd=float(group["median_odds"]))
            priced = price_team_total(consensus_quote, projection, float(group["median_odds"]))
            if priced is None:
                continue
            fair, ev_consensus = priced

            best_quote = replace(quote, odd=float(group["best_odds"]))
            best_priced = price_team_total(best_quote, projection, float(group["best_odds"]))
            ev_best = ev_consensus if best_priced is None else best_priced[1]

            row = {
                "fixture_id": fixture_id,
                "match": match,
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
                "home_mean": projection["home_mean"],
                "away_mean": projection["away_mean"],
                "transfer_reliability": reliability,
                "projection_source": source,
                "bet_id": quote.bet_id,
                "market_name": quote.market_name,
            }
            row["quality_score"] = quality_score(row)
            candidates.append(row)

        candidates.sort(key=lambda row: row["quality_score"], reverse=True)
        selected = candidates[0] if candidates else None
        output["fixtures"][str(fixture_id)] = {
            "match": match,
            "selected": selected,
            "top_candidates": candidates[: args.top_per_match],
        }

        print("=" * 92)
        print(match)
        if selected is None:
            print("  NO PRICED TEAM-TOTAL CANDIDATE FOUND IN CURRENT API ODDS")
            continue
        line = "" if selected["line"] is None else f" {selected['line']:g}"
        print(
            f"  PICK: {selected['stat']} | {selected['market_type']} | "
            f"{selected['selection'].upper()}{line}"
        )
        print(
            f"  fair {selected['model_fair']:.2f} | median {selected['median_book_odds']:.2f} "
            f"({selected['book_count']} books) | EV {selected['model_ev_consensus']:+.1%}"
        )
        print(
            f"  best {selected['best_book_odds']:.2f} ({selected['best_bookmaker']}) | "
            f"best EV {selected['model_ev_best']:+.1%} | rel {selected['transfer_reliability']} | "
            f"source {selected['projection_source']}"
        )
        print(
            f"  expected {selected['home_mean']:.2f}-{selected['away_mean']:.2f}"
        )

    path = save_json("match_cards", f"ucl_{date_key}_v01", output)
    print("\n" + "=" * 92)
    print(f"Saved per-match card to {path}")


if __name__ == "__main__":
    main()

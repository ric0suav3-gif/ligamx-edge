from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import FIXTURES, MATCH_DATE
from ingest.cache import load_json, save_json
from ingest.stat_odds import StatQuote, parse_stat_quotes
from model.selection import balanced_score
from model.stat_markets import asian_handicap, asian_match_total, asian_team_total, h2h
from model.stat_projection import SplitStatProfile, TeamStatProfile, project_stat
from scripts.predict_stat_markets import (
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
    """Consensus groups for every stat market the parser knows how to price."""
    grouped: dict[tuple[str, str, str, float | None], list[StatQuote]] = {}
    for quote in quotes:
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
    """Neutral opponent used only when API-Football has no usable domestic stat history."""
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
        source = "MODEL"
    else:
        home_transfer, away_transfer = 1.0, 1.0
        source = "ONE_SIDED_FALLBACK"

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
        "source": source,
    }


def price_market(
    quote: StatQuote,
    projection: dict[str, Any],
    odd: float,
) -> dict[str, float] | None:
    """Price team totals plus the joint market families supported by UCL Edge.

    Joint markets are only priced when both teams have real model inputs. This
    prevents a neutral proxy opponent from leaking into H2H/AH/match-total
    recommendations for limited-data fixtures such as Sabah.
    """
    kind = quote.market_type
    selection = quote.selection
    line = quote.line
    hm = float(projection["home_mean"])
    am = float(projection["away_mean"])
    r = projection["dispersion_r"]

    market = None
    if kind == "home_total":
        if line is None or not projection["home_real"]:
            return None
        market = asian_team_total(hm, float(line), selection, r)
    elif kind == "away_total":
        if line is None or not projection["away_real"]:
            return None
        market = asian_team_total(am, float(line), selection, r)
    elif kind == "match_total":
        if line is None or not (projection["home_real"] and projection["away_real"]):
            return None
        market = asian_match_total(hm, am, float(line), selection, r, r)
    elif kind == "handicap":
        if line is None or not (projection["home_real"] and projection["away_real"]):
            return None
        if selection == "home":
            market = asian_handicap(hm, am, float(line), r, r)
        elif selection == "away":
            market = asian_handicap(am, hm, float(line), r, r)
        else:
            return None
    elif kind == "h2h":
        if not (projection["home_real"] and projection["away_real"]):
            return None
        matchup = h2h(hm, am, r, r)
        if selection == "home":
            fair = matchup.fair_first
            win_eq = matchup.first_win
            loss_eq = matchup.second_win
            push = matchup.tie
        elif selection == "away":
            fair = matchup.fair_second
            win_eq = matchup.second_win
            loss_eq = matchup.first_win
            push = matchup.tie
        else:
            # The current H2H model treats ties as pushes. Do not pretend that
            # this prices a bookmaker's separate 3-way Draw selection.
            return None
        if fair is None:
            return None
        return {
            "fair": float(fair),
            "ev": offered_ev(float(odd), win_eq, loss_eq),
            "win_equivalent": float(win_eq),
            "loss_equivalent": float(loss_eq),
            "push": float(push),
            "decision_probability": float(win_eq / (win_eq + loss_eq)),
        }
    else:
        return None

    if market.fair_odds is None:
        return None
    decisions = market.win_equivalent + market.loss_equivalent
    decision_probability = (
        market.win_equivalent / decisions if decisions > 1e-12 else 0.0
    )
    return {
        "fair": float(market.fair_odds),
        "ev": offered_ev(float(odd), market.win_equivalent, market.loss_equivalent),
        "win_equivalent": float(market.win_equivalent),
        "loss_equivalent": float(market.loss_equivalent),
        "push": float(market.push),
        "decision_probability": float(decision_probability),
    }


def choose_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose a practical straight without allowing raw longshot EV to dominate."""
    if not candidates:
        return None

    positive = [row for row in candidates if row["model_ev_consensus"] > 0]
    practical_positive = [
        row for row in positive if row["selection_band"] in {"CORE", "EXTENDED"}
    ]
    practical = [
        row for row in candidates if row["selection_band"] in {"CORE", "EXTENDED"}
    ]

    pool = practical_positive or positive or practical or candidates
    return max(pool, key=lambda row: row["quality_score"])


def market_text(row: dict[str, Any]) -> str:
    line = "" if row["line"] is None else f" {float(row['line']):g}"
    return f"{row['stat']} | {row['market_type']} | {row['selection'].upper()}{line}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rank the full API-Football UCL stat board and select one practical straight per match."
    )
    parser.add_argument("--min-books", type=int, default=2)
    parser.add_argument("--split-prior", type=float, default=12.0)
    parser.add_argument("--matchup-shrinkage", type=float, default=0.55)
    parser.add_argument("--top-per-match", type=int, default=10)
    args = parser.parse_args()

    date_key = MATCH_DATE.replace("-", "_")
    predictions = required("predictions", f"ucl_stat_{date_key}_v02")
    profiles = required("team_profiles", "ucl_2026")
    baselines = required("stat_baselines", "ucl_2026")
    transfers = load_json("stat_transfers", "ucl_2026")

    output: dict[str, Any] = {
        "date": MATCH_DATE,
        "version": "ucl-match-card-v0.2-balanced",
        "policy": (
            "One practical ranked stat selection per fixture. Raw EV remains visible, "
            "but longshots, low reliability, one-sided proxies and joint-independence "
            "markets receive explicit selection penalties rather than being hidden."
        ),
        "fixtures": {},
    }

    print(f"UCL EDGE — BALANCED FULL MATCH CARD — {MATCH_DATE}")
    print(
        "API-Football only. Full supported stat board. Straight selection favors practical fair-price bands; "
        "raw longshot EV cannot win the ranking by itself.\n"
    )

    for fixture_id, fixture in FIXTURES.items():
        home_id = int(fixture["home"]["id"])
        away_id = int(fixture["away"]["id"])
        match = f"{fixture['home']['name']} vs {fixture['away']['name']}"
        raw_odds = load_json("odds", f"fixture_{fixture_id}")
        groups = grouped_quotes(parse_stat_quotes(raw_odds or []))
        pred_fixture = predictions.get("fixtures", {}).get(str(fixture_id), {})
        all_candidates: list[dict[str, Any]] = []

        for group in groups:
            quote = group["template"]
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

            consensus = price_market(quote, projection, float(group["median_odds"]))
            if consensus is None:
                continue
            best = price_market(quote, projection, float(group["best_odds"]))
            if best is None:
                best = consensus

            row = {
                "fixture_id": fixture_id,
                "match": match,
                "stat": quote.stat,
                "market_type": quote.market_type,
                "selection": quote.selection,
                "line": quote.line,
                "model_fair": consensus["fair"],
                "decision_probability": consensus["decision_probability"],
                "push_probability": consensus["push"],
                "median_book_odds": float(group["median_odds"]),
                "best_book_odds": float(group["best_odds"]),
                "best_bookmaker": group["best"].bookmaker,
                "book_count": group["books"],
                "bookmakers": group["bookmakers"],
                "model_ev_consensus": consensus["ev"],
                "model_ev_best": best["ev"],
                "home_mean": projection["home_mean"],
                "away_mean": projection["away_mean"],
                "transfer_reliability": reliability,
                "projection_source": source,
                "bet_id": quote.bet_id,
                "market_name": quote.market_name,
                "joint_market": quote.market_type in {"match_total", "handicap", "h2h"},
            }
            grade = balanced_score(
                fair_odds=row["model_fair"],
                consensus_ev=row["model_ev_consensus"],
                books=row["book_count"],
                reliability=row["transfer_reliability"],
                market_type=row["market_type"],
                source=row["projection_source"],
            )
            row["selection_band"] = grade.band
            row["quality_score"] = grade.score
            row["flags"] = list(grade.flags)
            all_candidates.append(row)

        eligible = [row for row in all_candidates if row["book_count"] >= args.min_books]
        book_fallback = False
        if not eligible:
            eligible = all_candidates
            book_fallback = bool(eligible)

        eligible.sort(key=lambda row: row["quality_score"], reverse=True)
        selected = choose_candidate(eligible)
        raw_ev_top = max(eligible, key=lambda row: row["model_ev_consensus"]) if eligible else None
        output["fixtures"][str(fixture_id)] = {
            "match": match,
            "selected": selected,
            "raw_ev_top": raw_ev_top,
            "one_book_fallback": book_fallback,
            "top_candidates": eligible[: args.top_per_match],
        }

        print("=" * 112)
        print(match)
        if selected is None:
            print("  NO PARSEABLE STAT MARKET IN CURRENT API ODDS")
            continue

        fallback_note = " | ONE-BOOK FALLBACK" if book_fallback else ""
        print(f"  SELECTED: {market_text(selected)}{fallback_note}")
        print(
            f"  fair {selected['model_fair']:.2f} | model decision {selected['decision_probability']:.1%} | "
            f"median {selected['median_book_odds']:.2f} ({selected['book_count']} books) | "
            f"EV {selected['model_ev_consensus']:+.1%}"
        )
        print(
            f"  best {selected['best_book_odds']:.2f} ({selected['best_bookmaker']}) | "
            f"best EV {selected['model_ev_best']:+.1%} | band {selected['selection_band']} | "
            f"rel {selected['transfer_reliability']} | source {selected['projection_source']}"
        )
        print(
            f"  expected {selected['home_mean']:.2f}-{selected['away_mean']:.2f} | "
            f"flags {','.join(selected['flags']) if selected['flags'] else 'none'}"
        )

        if raw_ev_top is not None and raw_ev_top is not selected:
            print(
                f"  RAW-EV TOP (not auto-selected): {market_text(raw_ev_top)} | "
                f"fair {raw_ev_top['model_fair']:.2f} | median {raw_ev_top['median_book_odds']:.2f} | "
                f"EV {raw_ev_top['model_ev_consensus']:+.1%} | band {raw_ev_top['selection_band']}"
            )

        print(f"\n  TOP {min(args.top_per_match, len(eligible))} BALANCED CANDIDATES")
        for idx, row in enumerate(eligible[: args.top_per_match], start=1):
            flag = f" [{','.join(row['flags'])}]" if row["flags"] else ""
            print(
                f"    {idx:2d}. {market_text(row):43s} | fair {row['model_fair']:5.2f} | "
                f"p {row['decision_probability']:5.1%} | med {row['median_book_odds']:5.2f} | "
                f"EV {row['model_ev_consensus']:+6.1%} | best {row['best_book_odds']:5.2f} "
                f"{row['best_bookmaker']} | {row['selection_band']}/{row['transfer_reliability']}{flag}"
            )

    path = save_json("match_cards", f"ucl_{date_key}_v02_balanced", output)
    print("\n" + "=" * 112)
    print(f"Saved balanced per-match card to {path}")


if __name__ == "__main__":
    main()

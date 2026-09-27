from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import FIXTURES, MATCH_DATE
from ingest.cache import load_json
from ingest.stat_odds import StatQuote, parse_stat_quotes
from model.distributions import count_distribution
from model.stat_markets import asian_handicap, asian_match_total, asian_team_total, h2h
from scripts.predict_stat_markets import PRIMARY_STATS
from scripts.rank_ucl_match_cards import projection_for_stat

TEMPLATE = ROOT / "web" / "ucl_mobile_template.html"
DEFAULT_OUTPUT = ROOT / "UCL_Edge_iPhone.html"
STAT_LABELS = {
    "shots": "Tiros",
    "shots_on_target": "Tiros a puerta",
    "corners": "Córners",
    "fouls": "Faltas",
    "offsides": "Fuera de juego",
    "yellow": "Amarillas",
}


def line_key(line: float | None) -> str:
    if line is None:
        return ""
    return f"{float(line):g}"


def grouped_quotes(quotes: list[StatQuote]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, float | None], list[StatQuote]] = {}
    for quote in quotes:
        key = (quote.stat, quote.market_type, quote.selection, quote.line)
        grouped.setdefault(key, []).append(quote)

    out: list[dict[str, Any]] = []
    for key, items in grouped.items():
        prices = [float(q.odd) for q in items]
        books = sorted({q.bookmaker for q in items})
        best = max(items, key=lambda q: q.odd)
        out.append(
            {
                "stat": key[0],
                "market_type": key[1],
                "selection": key[2],
                "line": key[3],
                "median": float(statistics.median(prices)),
                "best": float(best.odd),
                "best_book": best.bookmaker,
                "books": len(books),
                "bookmakers": books,
                "bet_id": best.bet_id,
                "market_name": best.market_name,
            }
        )
    return out


def offered_ev(odd: float, win_eq: float, loss_eq: float) -> float:
    return win_eq * (odd - 1.0) - loss_eq


def price_group(group: dict[str, Any], stat: dict[str, Any]) -> dict[str, Any] | None:
    kind = group["market_type"]
    selection = group["selection"]
    line = group["line"]
    hm = float(stat["home_mean"])
    am = float(stat["away_mean"])
    r = stat.get("dispersion_r")
    r = None if r is None else float(r)

    fair: float | None = None
    win_eq = loss_eq = 0.0
    if kind == "home_total" and line is not None:
        m = asian_team_total(hm, float(line), selection, r)
        fair, win_eq, loss_eq = m.fair_odds, m.win_equivalent, m.loss_equivalent
    elif kind == "away_total" and line is not None:
        m = asian_team_total(am, float(line), selection, r)
        fair, win_eq, loss_eq = m.fair_odds, m.win_equivalent, m.loss_equivalent
    elif kind == "match_total" and line is not None:
        m = asian_match_total(hm, am, float(line), selection, r, r)
        fair, win_eq, loss_eq = m.fair_odds, m.win_equivalent, m.loss_equivalent
    elif kind == "handicap" and line is not None:
        if selection == "home":
            m = asian_handicap(hm, am, float(line), r, r)
        elif selection == "away":
            m = asian_handicap(am, hm, float(line), r, r)
        else:
            return None
        fair, win_eq, loss_eq = m.fair_odds, m.win_equivalent, m.loss_equivalent
    elif kind == "h2h":
        m = h2h(hm, am, r, r)
        probs = {"home": m.first_win, "away": m.second_win}
        if selection not in probs:
            return None
        p = probs[selection]
        push = m.tie
        fair = None if p <= 1e-12 else (1.0 - push) / p
        win_eq, loss_eq = p, 1.0 - p - push
    else:
        return None

    if fair is None:
        return None
    row = dict(group)
    row["fair"] = float(fair)
    row["ev_median"] = offered_ev(float(group["median"]), win_eq, loss_eq)
    row["ev_best"] = offered_ev(float(group["best"]), win_eq, loss_eq)
    return row


def reliability_weight(level: str) -> float:
    return {"HIGH": 0.018, "MEDIUM": 0.009, "LOW": -0.025}.get(level, -0.01)


def build_payload() -> dict[str, Any]:
    date_key = MATCH_DATE.replace("-", "_")
    predictions = load_json("predictions", f"ucl_stat_{date_key}_v02")
    if predictions is None:
        raise SystemExit(
            f"Missing predictions/ucl_stat_{date_key}_v02.json. Run predict_stat_markets.py first."
        )
    profiles = load_json("team_profiles", "ucl_2026")
    baselines = load_json("stat_baselines", "ucl_2026")
    transfers = load_json("stat_transfers", "ucl_2026")
    if profiles is None or baselines is None:
        raise SystemExit("Missing team_profiles or stat_baselines cache.")

    fixtures_out: list[dict[str, Any]] = []
    global_candidates: list[dict[str, Any]] = []

    for fixture_id, fixture in FIXTURES.items():
        home_id = int(fixture["home"]["id"])
        away_id = int(fixture["away"]["id"])
        pred_fixture = predictions.get("fixtures", {}).get(str(fixture_id), {})
        raw_odds = load_json("odds", f"fixture_{fixture_id}") or []
        groups = grouped_quotes(parse_stat_quotes(raw_odds))

        stats_out: dict[str, Any] = {}
        for stat_name in PRIMARY_STATS:
            row = pred_fixture.get("stats", {}).get(stat_name)
            source = "FULL_MODEL"
            if row is not None:
                rel = row.get("transfer_reliability", {})
                level = str(rel.get("level") or "UNKNOWN")
                reason = str(rel.get("reason") or "")
                stat_out = {
                    "home_mean": float(row["home_mean"]),
                    "away_mean": float(row["away_mean"]),
                    "dispersion_r": None if row.get("dispersion_r") is None else float(row["dispersion_r"]),
                    "reliability": level,
                    "reason": reason,
                    "source": source,
                    "home_real": True,
                    "away_real": True,
                }
            else:
                fallback = projection_for_stat(
                    home_id,
                    away_id,
                    stat_name,
                    profiles,
                    baselines,
                    transfers,
                    12.0,
                    0.55,
                )
                if fallback is None:
                    continue
                source = str(fallback.get("source") or "FALLBACK")
                stat_out = {
                    "home_mean": float(fallback["home_mean"]),
                    "away_mean": float(fallback["away_mean"]),
                    "dispersion_r": fallback.get("dispersion_r"),
                    "reliability": "LOW" if source == "ONE_SIDED_FALLBACK" else "UNKNOWN",
                    "reason": "One side has insufficient API-Football domestic stat history; neutral UCL baseline proxy used." if source == "ONE_SIDED_FALLBACK" else source,
                    "source": source,
                    "home_real": bool(fallback.get("home_real")),
                    "away_real": bool(fallback.get("away_real")),
                }

            stat_out["home_dist"] = count_distribution(
                stat_out["home_mean"], stat_out["dispersion_r"]
            )
            stat_out["away_dist"] = count_distribution(
                stat_out["away_mean"], stat_out["dispersion_r"]
            )
            stats_out[stat_name] = stat_out

        odds_map: dict[str, Any] = {}
        candidates: list[dict[str, Any]] = []
        for group in groups:
            key = "|".join(
                [
                    group["stat"],
                    group["market_type"],
                    group["selection"],
                    line_key(group["line"]),
                ]
            )
            odds_map[key] = group
            stat = stats_out.get(group["stat"])
            if stat is None:
                continue
            priced = price_group(group, stat)
            if priced is None:
                continue
            priced["fixture_id"] = str(fixture_id)
            priced["match"] = f"{fixture['home']['name']} vs {fixture['away']['name']}"
            priced["home"] = fixture["home"]["name"]
            priced["away"] = fixture["away"]["name"]
            priced["reliability"] = stat["reliability"]
            priced["source"] = stat["source"]
            priced["home_mean"] = stat["home_mean"]
            priced["away_mean"] = stat["away_mean"]
            priced["score"] = (
                priced["ev_median"]
                + reliability_weight(stat["reliability"])
                + min(priced["books"], 5) * 0.003
            )
            candidates.append(priced)
            global_candidates.append(priced)

        candidates.sort(key=lambda x: x["score"], reverse=True)
        fixtures_out.append(
            {
                "id": str(fixture_id),
                "home": fixture["home"]["name"],
                "away": fixture["away"]["name"],
                "stats": stats_out,
                "odds": odds_map,
                "picks": candidates[:12],
            }
        )

    global_candidates.sort(key=lambda x: x["score"], reverse=True)

    tracker_path = ROOT / "tracking" / "ucl_results.json"
    tracker = None
    if tracker_path.exists():
        try:
            tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            tracker = None

    return {
        "meta": {
            "league": "UEFA Champions League",
            "date": MATCH_DATE,
            "version": "ucl-edge-mobile-v1",
            "source": "API-Football caches generated by the UCL Edge pipeline",
            "method": "Domestic for/against rates -> domestic league normalization -> opponent adjustment -> proper-stage UCL stat transfer -> UCL environment -> count distribution -> fair markets.",
            "note": "Odds are a build-time API-Football snapshot. Rebuild the page to refresh prices. LOW/proxy markets remain visible but are explicitly flagged.",
        },
        "stat_labels": STAT_LABELS,
        "fixtures": fixtures_out,
        "global_picks": global_candidates[:40],
        "tracker": tracker,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a self-contained LigaMX-v29-style UCL Edge mobile HTML from API-Football caches."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    args = parser.parse_args()

    if not args.template.exists():
        raise SystemExit(f"Missing UI template: {args.template}")

    payload = build_payload()
    template = args.template.read_text(encoding="utf-8")
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = template.replace("__UCL_DATA__", blob)
    if "__UCL_DATA__" in html:
        raise SystemExit("Template placeholder was not replaced.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"Built {args.output}")
    print(f"Date: {MATCH_DATE} | fixtures: {len(payload['fixtures'])}")
    print(f"Embedded ranked API market quotes: {len(payload['global_picks'])}")
    print("No API key or .env value is embedded in the page.")


if __name__ == "__main__":
    main()

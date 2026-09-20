from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.cache import load_json
from scripts.build_ucl_mobile_ui import DEFAULT_OUTPUT, TEMPLATE, build_payload


AH_BUGGY = "function move(bucket,key,d){state[bucket][key]=Math.max(0,+(state[bucket][key]+d).toFixed(2));render();}"
AH_FIXED = "function move(bucket,key,d){const n=+(state[bucket][key]+d).toFixed(2);state[bucket][key]=bucket==='ah'?n:Math.max(0,n);render();}"


def to_ui_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """Translate balanced-ranker rows into the shape used by the mobile Picks tab."""
    return {
        "fixture_id": str(row["fixture_id"]),
        "match": row["match"],
        "home": row.get("match", "").split(" vs ", 1)[0],
        "away": row.get("match", "").split(" vs ", 1)[1] if " vs " in row.get("match", "") else "",
        "stat": row["stat"],
        "market_type": row["market_type"],
        "selection": row["selection"],
        "line": row.get("line"),
        "fair": float(row["model_fair"]),
        "median": float(row["median_book_odds"]),
        "best": float(row["best_book_odds"]),
        "best_book": row["best_bookmaker"],
        "books": int(row["book_count"]),
        "bookmakers": row.get("bookmakers", []),
        "ev_median": float(row["model_ev_consensus"]),
        "ev_best": float(row["model_ev_best"]),
        "home_mean": float(row["home_mean"]),
        "away_mean": float(row["away_mean"]),
        "reliability": row["transfer_reliability"],
        "source": row["projection_source"],
        "score": float(row["quality_score"]),
        "selection_band": row.get("selection_band"),
        "flags": row.get("flags", []),
        "bet_id": row.get("bet_id"),
        "market_name": row.get("market_name"),
    }


def apply_balanced_rankings(payload: dict[str, Any]) -> bool:
    """Use the v0.2 balanced match-card cache when it exists.

    The fair-market explorer remains unchanged. This only changes the Picks tab
    and global ranking so extreme low-probability EV outliers do not dominate.
    """
    date_key = payload["meta"]["date"].replace("-", "_")
    card = load_json("match_cards", f"ucl_{date_key}_v02_balanced")
    if not card:
        return False

    card_fixtures = card.get("fixtures", {})
    global_rows: list[dict[str, Any]] = []
    for fixture in payload.get("fixtures", []):
        ranked = card_fixtures.get(str(fixture["id"]))
        if not ranked:
            continue
        rows = [to_ui_candidate(row) for row in ranked.get("top_candidates", [])]
        fixture["picks"] = rows
        selected = ranked.get("selected")
        fixture["selected_pick"] = to_ui_candidate(selected) if selected else None
        global_rows.extend(rows)

    global_rows.sort(key=lambda row: row.get("score", -999.0), reverse=True)
    payload["global_picks"] = global_rows[:60]
    payload["meta"]["selection_layer"] = "v0.2 balanced V29-style"
    payload["meta"]["selection_note"] = (
        "Raw EV is displayed but practical fair-price bands, bookmaker depth, "
        "reliability and joint/proxy penalties drive the Picks ranking."
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the self-contained UCL Edge iPhone page from today's local API-Football caches."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = build_payload()
    balanced = apply_balanced_rankings(payload)

    template = TEMPLATE.read_text(encoding="utf-8")
    template = template.replace(AH_BUGGY, AH_FIXED)

    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = template.replace("__UCL_DATA__", blob)
    if "__UCL_DATA__" in html:
        raise SystemExit("UI data placeholder was not replaced")

    args.output.write_text(html, encoding="utf-8")
    print(f"Refreshed {args.output}")
    print(f"Slate: {payload['meta']['date']} | fixtures={len(payload['fixtures'])}")
    print(f"Current API-Football market candidates embedded={len(payload['global_picks'])}")
    print(f"Balanced Picks layer: {'yes' if balanced else 'no (run rank_ucl_match_cards.py first)'}")
    print("Secrets embedded: none")


if __name__ == "__main__":
    main()

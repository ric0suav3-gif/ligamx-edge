from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient

DEFAULT_HTML = ROOT / "NFL_Edge_iPhone.html"


def extract_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker = "const D="
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"Could not find embedded Sunday payload in {path}")
    start += len(marker)
    end = text.find(";\n", start)
    if end < 0:
        raise SystemExit("Could not find end of embedded Sunday payload")
    return json.loads(text[start:end])


def game_score(row: dict[str, Any]) -> tuple[float | None, float | None]:
    scores = row.get("scores") or {}
    if isinstance(scores, dict):
        home = scores.get("home")
        away = scores.get("away")
        def total(v: Any) -> float | None:
            if isinstance(v, dict):
                for key in ("total", "points", "score"):
                    if v.get(key) is not None:
                        try:
                            return float(v[key])
                        except (TypeError, ValueError):
                            pass
            try:
                return None if v is None else float(v)
            except (TypeError, ValueError):
                return None
        h, a = total(home), total(away)
        if h is not None and a is not None:
            return h, a

    # Defensive fallbacks for provider schema changes.
    game = row.get("game") or row
    for hk, ak in (("home_score", "away_score"), ("score_home", "score_away")):
        if game.get(hk) is not None and game.get(ak) is not None:
            return float(game[hk]), float(game[ak])
    return None, None


def status_short(row: dict[str, Any]) -> str:
    game = row.get("game") or row
    status = game.get("status") or row.get("status") or {}
    if isinstance(status, dict):
        return str(status.get("short") or status.get("long") or "")
    return str(status)


def grade_market(pick: dict[str, Any], home_score: float, away_score: float) -> str:
    scope = str(pick.get("scope"))
    side = str(pick.get("side"))
    line = float(pick.get("line"))
    if scope == "home_total":
        actual = home_score
    elif scope == "away_total":
        actual = away_score
    elif scope == "match_total":
        actual = home_score + away_score
    else:
        return "UNSUPPORTED"
    if math.isclose(actual, line, abs_tol=1e-9):
        return "PUSH"
    won = actual > line if side == "over" else actual < line
    return "WIN" if won else "LOSS"


def units_for(result: str, odd: float) -> float:
    if result == "WIN":
        return odd - 1.0
    if result == "LOSS":
        return -1.0
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Grade the currently embedded NFL Sunday card with API-Sports game results.")
    ap.add_argument("--html", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    html = args.html if args.html.is_absolute() else ROOT / args.html
    payload = extract_payload(html)
    prior_date = str((payload.get("meta") or {}).get("date") or "unknown")
    client = APINFLClient()

    game_cache: dict[str, tuple[float, float]] = {}
    def score_for(game_id: str) -> tuple[float, float] | None:
        if game_id in game_cache:
            return game_cache[game_id]
        rows = client.games(id=game_id).response
        if not rows:
            return None
        row = rows[0]
        status = status_short(row).upper()
        h, a = game_score(row)
        if h is None or a is None or status not in {"FT", "AET", "FINAL", "CLOSED"}:
            return None
        game_cache[game_id] = (h, a)
        return h, a

    straights = []
    straight_units = 0.0
    wins = losses = pushes = 0
    for pick in payload.get("straights") or []:
        gid = str(pick["game_id"])
        score = score_for(gid)
        if score is None:
            result = "PENDING"
            h = a = None
            units = 0.0
        else:
            h, a = score
            result = grade_market(pick, h, a)
            units = units_for(result, float(pick.get("median_odd") or 1.0))
            if result == "WIN": wins += 1
            elif result == "LOSS": losses += 1
            elif result == "PUSH": pushes += 1
        straight_units += units
        straights.append({
            **pick,
            "result": result,
            "home_score": h,
            "away_score": a,
            "units": round(units, 4),
        })

    parlays = []
    parlay_units = 0.0
    for parlay in payload.get("parlays") or []:
        leg_results = []
        for leg in parlay.get("legs") or []:
            score = score_for(str(leg["game_id"]))
            leg_results.append("PENDING" if score is None else grade_market(leg, *score))
        if any(x == "LOSS" for x in leg_results):
            result = "LOSS"
        elif all(x in {"WIN", "PUSH"} for x in leg_results) and any(x == "WIN" for x in leg_results):
            result = "WIN"
        elif all(x == "PUSH" for x in leg_results):
            result = "PUSH"
        else:
            result = "PENDING"
        units = units_for(result, float(parlay.get("price") or 1.0))
        parlay_units += units
        parlays.append({**parlay, "leg_results": leg_results, "result": result, "units": round(units, 4)})

    decided = wins + losses
    report = {
        "source": "API-Sports American Football",
        "date": prior_date,
        "straight_record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "straight_units": round(straight_units, 4),
        "straight_roi": round(straight_units / decided, 4) if decided else None,
        "straights": straights,
        "parlay_units": round(parlay_units, 4),
        "parlays": parlays,
        "note": "1 unit per straight/parlay at the embedded median price.",
    }

    output = args.output or (ROOT / "exports" / f"nfl_grade_{prior_date.replace('-', '_')}_api.json")
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Graded {prior_date} with API-Sports")
    print(f"Straights: {report['straight_record']} | units {report['straight_units']:+.2f} | ROI {((report['straight_roi'] or 0)*100):+.1f}%")
    for row in straights:
        print(f"  {row['result']:7s} | {row['market']} | {row['away_score']}-{row['home_score']} | {row['units']:+.2f}u")
    print(f"Parlays: units {report['parlay_units']:+.2f}")
    for i,row in enumerate(parlays,1):
        print(f"  P{i}: {row['result']} | legs={','.join(row['leg_results'])} | {row['units']:+.2f}u")
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()

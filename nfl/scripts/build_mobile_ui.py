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

from nfl.ingest.cache import load_json

TEMPLATE = ROOT / "nfl" / "web" / "nfl_mobile_template.html"
DEFAULT_OUTPUT = ROOT / "NFL_Edge_iPhone.html"

STAT_FIELDS = [
    ("Jugadas", "expected_plays"),
    ("Intentos de pase", "expected_pass_attempts"),
    ("Completos", "expected_completions"),
    ("Yardas de pase", "expected_passing_yards"),
    ("Acarreos", "expected_rush_attempts"),
    ("Yardas terrestres", "expected_rushing_yards"),
    ("Capturas", "expected_sacks_made"),
    ("Pérdidas", "expected_turnovers"),
    ("Puntos", "expected_points"),
]


def require_cache(kind: str, key: str) -> dict[str, Any]:
    value = load_json(kind, key)
    if value is None:
        raise SystemExit(f"Missing nfl/data/cache/{kind}/{key}.json")
    return value


def approximate_moneyline(
    home: dict[str, Any],
    away: dict[str, Any],
    home_odd: float | None,
    away_odd: float | None,
) -> list[dict[str, Any]]:
    if home_odd is None or away_odd is None:
        return []
    variance = float(home["points_sd"]) ** 2 + float(away["points_sd"]) ** 2
    if variance <= 0:
        return []
    z = (float(home["expected_points"]) - float(away["expected_points"])) / math.sqrt(variance)
    home_p = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    rows = [
        ("home", home, home_p, home_odd),
        ("away", away, 1.0 - home_p, away_odd),
    ]
    return [
        {
            "side": side,
            "team": projection["team_name"],
            "win_prob": probability,
            "fair": 1.0 / probability,
            "book_odds": odd,
            "ev": probability * odd - 1.0,
        }
        for side, projection, probability, odd in rows
    ]


def build_payload(
    *,
    game_id: str,
    context: dict[str, Any],
    team_predictions: dict[str, Any],
    comparisons: dict[str, Any],
    props: dict[str, Any],
    date: str,
    kickoff: str,
    venue: str,
    home_odd: float | None,
    away_odd: float | None,
) -> dict[str, Any]:
    projections = team_predictions.get("projections") or []
    by_side = {row["side"]: row for row in projections}
    if set(by_side) != {"home", "away"}:
        raise SystemExit("Team prediction JSON must contain home and away projections.")
    home = by_side["home"]
    away = by_side["away"]
    home_points = float(home["expected_points"])
    away_points = float(away["expected_points"])

    histories = context.get("histories") or {}
    history_counts = [len(row.get("matches") or []) for row in histories.values()]
    history_note = " + ".join(str(value) for value in history_counts) + " juegos previos"

    stats = [
        {
            "label": label,
            "field": field,
            "away": float(away[field]),
            "home": float(home[field]),
        }
        for label, field in STAT_FIELDS
    ]

    market_rows = list(comparisons.get("rows") or [])
    market_rows.sort(key=lambda row: float(row.get("consensus_ev") or -999), reverse=True)
    prop_rows = list(props.get("rows") or [])

    return {
        "meta": {
            "date": date,
            "game_id": str(game_id),
            "kickoff": kickoff,
            "venue": venue,
            "version": "nfl-edge-mobile-v1",
            "method": "EWMA con media vida de 8 juegos, ajuste ataque/defensa y distribuciones por mercado.",
            "history_note": history_note,
            "source": "API-Sports NFL · snapshot prepartido",
            "note": (
                "La etiqueta HIGH indica cobertura suficiente del historial, no validación de rentabilidad. "
                "Los totales de partido suponen independencia entre equipos. La moneyline es una aproximación "
                "normal derivada de puntos esperados y desviaciones, no un modelo moneyline calibrado."
            ),
        },
        "game": {
            "away": away["team_name"],
            "home": home["team_name"],
            "away_points": away_points,
            "home_points": home_points,
            "home_margin": home_points - away_points,
            "total": home_points + away_points,
            "away_reliability": away.get("reliability"),
            "home_reliability": home.get("reliability"),
        },
        "moneyline": approximate_moneyline(home, away, home_odd, away_odd),
        "stats": stats,
        "team_markets": market_rows,
        "player_props": prop_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the standalone NFL Edge iPhone page.")
    parser.add_argument("--game", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--kickoff", default="Hora por confirmar")
    parser.add_argument("--venue", default="Sede por confirmar")
    parser.add_argument("--home-odds", type=float)
    parser.add_argument("--away-odds", type=float)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    context = require_cache("contexts", f"game_{args.game}")
    team_predictions = require_cache("predictions", f"team_stats_game_{args.game}_v01")
    comparisons = require_cache("comparisons", f"team_game_{args.game}_v01")
    props = require_cache("predictions", f"core_game_{args.game}_v01")
    payload = build_payload(
        game_id=args.game,
        context=context,
        team_predictions=team_predictions,
        comparisons=comparisons,
        props=props,
        date=args.date,
        kickoff=args.kickoff,
        venue=args.venue,
        home_odd=args.home_odds,
        away_odd=args.away_odds,
    )

    template = TEMPLATE.read_text(encoding="utf-8")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("</", "<\\/")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__NFL_DATA__", encoded), encoding="utf-8")
    print(f"Built {output}")
    print(
        f"{payload['game']['away']} {payload['game']['away_points']:.2f} @ "
        f"{payload['game']['home']} {payload['game']['home_points']:.2f} | "
        f"markets={len(payload['team_markets'])} props={len(payload['player_props'])}"
    )


if __name__ == "__main__":
    main()

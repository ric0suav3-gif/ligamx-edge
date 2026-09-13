from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.cache import load_json
from nfl.model.selection import select_straights, select_two_leg_parlays

TEMPLATE = ROOT / "nfl" / "web" / "nfl_sunday_template.html"
DEFAULT_OUTPUT = ROOT / "NFL_Edge_iPhone.html"

STAT_LABELS = {
    "points": "Puntos",
    "pass_attempts": "Intentos de pase",
    "pass_completions": "Completos",
    "passing_yards": "Yardas de pase",
    "rush_attempts": "Acarreos",
    "rushing_yards": "Yardas terrestres",
    "sacks": "Capturas",
    "turnovers": "Pérdidas",
}

PREVIOUS_GRADE = {
    "game": "San Francisco 49ers @ Los Angeles Rams",
    "result": "49ers 27–7 Rams",
    "straight_record": "1–2",
    "straight_units": -1.10,
    "picks": [
        {"name": "Total Over 44.5", "result": "LOSS", "actual": "34 puntos"},
        {"name": "Brock Purdy Over 15.5 rush", "result": "WIN", "actual": "29 yardas"},
        {"name": "Kyren Williams Over 57.5 rush", "result": "LOSS", "actual": "41 yardas"},
        {"name": "Parlay conservador (3 legs)", "result": "LOSS", "actual": "Falló el total"},
        {"name": "Cuotón", "result": "LOSS", "actual": "Fallaron total y Kyren"},
    ],
    "adjustment": (
        "No se reentrenó el motor por un solo partido. La selección ahora elimina "
        "colas de baja probabilidad, exige respaldo de al menos tres casas, prioriza "
        "probabilidad sobre EV bruto y limita una jugada por partido."
    ),
}


def _game_id(row: dict[str, Any]) -> str:
    game = row.get("game") or row
    return str(row.get("id") or game.get("id"))


def _team_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("nickname") or value.get("id") or "?")
    return str(value or "?")


def game_info(row: dict[str, Any]) -> dict[str, Any]:
    game = row.get("game") or row
    teams = row.get("teams") or {}
    date = game.get("date") or row.get("date") or {}
    if isinstance(date, dict):
        kickoff = str(date.get("time") or "TBD")
        timezone_name = str(date.get("timezone") or "America/New_York")
    else:
        kickoff = str(date)
        timezone_name = ""
    return {
        "game_id": _game_id(row),
        "away": _team_name(teams.get("away") or row.get("away")),
        "home": _team_name(teams.get("home") or row.get("home")),
        "kickoff": kickoff,
        "timezone": timezone_name,
    }


def market_name(row: dict[str, Any], game: dict[str, Any]) -> str:
    scope = str(row.get("scope"))
    if scope == "home_total":
        owner = game["home"]
    elif scope == "away_total":
        owner = game["away"]
    else:
        owner = "Partido"
    side = "Más" if row.get("side") == "over" else "Menos"
    stat = STAT_LABELS.get(str(row.get("stat")), str(row.get("stat")))
    return f"{owner} · {stat} · {side} {float(row['line']):g}"


def build_payload(
    date: str,
    slate: list[dict[str, Any]],
    excluded_games: set[str] | None = None,
    exclusion_note: str = "",
) -> dict[str, Any]:
    excluded_games = excluded_games or set()
    games = {game["game_id"]: game for game in map(game_info, slate)}
    market_rows: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []

    for game_id, game in games.items():
        prediction = load_json("predictions", f"team_stats_game_{game_id}_v01")
        comparison = load_json("comparisons", f"team_game_{game_id}_v01")
        if prediction:
            by_side = {row["side"]: row for row in prediction.get("projections") or []}
            if set(by_side) == {"away", "home"}:
                away_points = float(by_side["away"]["expected_points"])
                home_points = float(by_side["home"]["expected_points"])
                projections.append(
                    {
                        **game,
                        "away_points": away_points,
                        "home_points": home_points,
                        "total": away_points + home_points,
                        "lean": game["home"] if home_points >= away_points else game["away"],
                        "margin": abs(home_points - away_points),
                    }
                )
        for row in (comparison or {}).get("rows") or []:
            if game_id in excluded_games:
                continue
            market_rows.append(
                {
                    **row,
                    **game,
                    "market": market_name(row, game),
                    "probability": 1.0 / float(row["fair"]),
                }
            )

    straights = select_straights(market_rows, limit=5)
    parlays = select_two_leg_parlays(market_rows, limit=3)
    return {
        "meta": {
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "version": "nfl-edge-sunday-v1.1",
            "games": len(games),
            "priced_games": len({row["game_id"] for row in market_rows}),
            "exclusion_note": exclusion_note,
            "rules": (
                "Straights: cuota mediana 1.60–1.80, probabilidad modelo ≥62%, "
                "EV ≥5%, ≥3 casas y máximo una por partido. Parlays: dos partidos "
                "distintos, cada leg ≥75% y cuota total 1.60–1.80."
            ),
        },
        "straights": straights,
        "parlays": parlays,
        "projections": sorted(projections, key=lambda row: (row["kickoff"], row["game_id"])),
        "grade": PREVIOUS_GRADE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the NFL Sunday iPhone card.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--exclude-game",
        action="append",
        default=[],
        help="Game ID to omit from recommendations after the injury screen (repeatable).",
    )
    parser.add_argument("--exclusion-note", default="")
    args = parser.parse_args()

    slate = load_json("audits", f"slate_{args.date}")
    if not slate:
        raise SystemExit(f"Missing slate cache for {args.date}; run audit_day.py first.")
    payload = build_payload(
        args.date,
        slate,
        excluded_games=set(args.exclude_game),
        exclusion_note=args.exclusion_note,
    )
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE.read_text(encoding="utf-8")
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.write_text(template.replace("__NFL_SLATE_DATA__", encoded), encoding="utf-8")
    print(
        f"Built {output} | games={payload['meta']['games']} "
        f"priced={payload['meta']['priced_games']} straights={len(payload['straights'])} "
        f"parlays={len(payload['parlays'])}"
    )


if __name__ == "__main__":
    main()

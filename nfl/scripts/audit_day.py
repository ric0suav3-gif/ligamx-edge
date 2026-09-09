from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.config.nfl_2026 import NFL_LEAGUE_ID, SEASON
from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import save_json


def team_name(side: Any) -> str:
    if isinstance(side, dict):
        return str(side.get("name") or side.get("nickname") or side.get("id") or "?")
    return str(side)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit one NFL slate from API-Sports.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--season", type=int, default=SEASON)
    parser.add_argument("--league", type=int, default=NFL_LEAGUE_ID)
    parser.add_argument("--timezone", default="America/New_York")
    args = parser.parse_args()

    client = APINFLClient()
    rows = client.games(
        league=args.league,
        season=args.season,
        date=args.date,
        timezone=args.timezone,
    ).response

    print(f"NFL slate {args.date} | games={len(rows)}\n")
    for row in rows:
        game = row.get("game") or row
        game_id = row.get("id") or game.get("id")

        teams = row.get("teams") or {}
        home = teams.get("home") or row.get("home") or {}
        away = teams.get("away") or row.get("away") or {}

        game_date = game.get("date") or row.get("date")
        status = game.get("status") or row.get("status")

        print(
            f"{game_id} | {team_name(away)} @ {team_name(home)} | "
            f"{game_date} | status={status}"
        )

    path = save_json("audits", f"slate_{args.date}", rows)
    print(f"\nSaved raw slate to {path}")


if __name__ == "__main__":
    main()

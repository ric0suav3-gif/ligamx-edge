from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.config.nfl_2026 import NFL_LEAGUE_ID, SEASON
from nfl.ingest.api_sports import APINFLClient


def main() -> None:
    client = APINFLClient()

    rows = client.leagues(id=NFL_LEAGUE_ID, season=SEASON).response
    if not rows:
        raise SystemExit(
            f"No NFL league row returned for league={NFL_LEAGUE_ID}, season={SEASON}."
        )

    league = rows[0]
    print("NFL API connection: OK")
    print(f"league: {league.get('league', {}).get('name')} | id={NFL_LEAGUE_ID}")
    print(f"season: {SEASON}")

    seasons = league.get("seasons") or []
    season_row = next(
        (row for row in seasons if int(row.get("year") or 0) == SEASON),
        None,
    )
    if season_row:
        print("coverage:")
        print(season_row.get("coverage"))
    else:
        print("coverage: season row not found in response")


if __name__ == "__main__":
    main()

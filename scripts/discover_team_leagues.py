from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import SEASON, TEAMS, UCL_LEAGUE_ID
from ingest.api_football import APIFootballClient


def score_candidate(row: dict) -> tuple[int, str]:
    league = row.get("league", {})
    country = row.get("country", {})
    name = str(league.get("name") or "")
    league_type = str(league.get("type") or "")
    country_name = str(country.get("name") or "")

    score = 0
    if league_type.lower() == "league":
        score += 100
    if int(league.get("id") or 0) == UCL_LEAGUE_ID:
        score -= 1000

    lowered = name.lower()
    for token in ("champions league", "europa", "conference", "cup", "super cup", "friendly"):
        if token in lowered:
            score -= 200

    return score, f"{country_name} | {name}"


def main() -> None:
    client = APIFootballClient()

    print(f"Candidate domestic leagues for season {SEASON}\n")
    for team_id, team_name in sorted(TEAMS.items(), key=lambda x: x[1]):
        rows = client.leagues(team=team_id, season=SEASON).response
        ranked = sorted(rows, key=score_candidate, reverse=True)

        print(f"{team_name} ({team_id})")
        if not ranked:
            print("  NO LEAGUES RETURNED")
            continue

        for row in ranked[:8]:
            league = row.get("league", {})
            country = row.get("country", {})
            score, _ = score_candidate(row)
            print(
                f"  {league.get('id')} | {league.get('name')} | "
                f"{country.get('name')} | type={league.get('type')} | score={score}"
            )
        print()


if __name__ == "__main__":
    main()

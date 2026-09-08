from __future__ import annotations

import argparse
from datetime import date

from ingest.api_football import APIFootballClient
from ingest.coverage import flat_coverage
from ingest.fixtures import UCL_LEAGUE_ID, ucl_fixtures_for_date


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test API-Football for UCL Edge")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--season", type=int, default=date.today().year)
    args = parser.parse_args()

    client = APIFootballClient()

    print(f"UCL league id: {UCL_LEAGUE_ID}")
    print(f"Coverage for season {args.season}:")
    for key, value in sorted(
        flat_coverage(client, UCL_LEAGUE_ID, args.season).items()
    ):
        print(f"  {key}: {value}")

    fixtures = ucl_fixtures_for_date(client, args.date, args.season)
    print(f"\nFixtures on {args.date}: {len(fixtures)}")
    for row in fixtures:
        fixture = row.get("fixture", {})
        teams = row.get("teams", {})
        print(
            f"  {fixture.get('id')}: "
            f"{teams.get('home', {}).get('name')} vs "
            f"{teams.get('away', {}).get('name')}"
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from datetime import date

from ingest.api_football import APIFootballClient
from ingest.fixtures import ucl_fixtures_for_date


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List UCL fixture/team IDs for one date."
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--season", type=int, default=date.today().year)
    args = parser.parse_args()

    client = APIFootballClient()
    fixtures = ucl_fixtures_for_date(client, args.date, args.season)

    if not fixtures:
        print("No UCL fixtures returned.")
        return

    for row in fixtures:
        fixture = row["fixture"]
        home = row["teams"]["home"]
        away = row["teams"]["away"]
        print(
            f"{fixture['id']} | "
            f"{home['name']} ({home['id']}) vs "
            f"{away['name']} ({away['id']}) | "
            f"{fixture['date']}"
        )


if __name__ == "__main__":
    main()

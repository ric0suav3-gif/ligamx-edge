from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import FIXTURES
from ingest.api_football import APIFootballClient
from ingest.statistics import parse_fixture_statistics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect one completed fixture's raw model statistics."
    )
    parser.add_argument("fixture_id", type=int)
    args = parser.parse_args()

    client = APIFootballClient()
    rows = client.fixture_statistics(args.fixture_id).response
    parsed = parse_fixture_statistics(rows)

    print(f"fixture={args.fixture_id}")
    if args.fixture_id in FIXTURES:
        print("NOTE: this is one of today's scheduled UCL fixtures; pre-match stats may be empty.")

    if not rows:
        print("No fixture statistics returned.")
        return

    for team_row in rows:
        team = team_row.get("team", {})
        team_id = team.get("id")
        print(f"\n{team.get('name')} ({team_id})")
        for key, value in sorted(parsed.get(int(team_id), {}).items()):
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()

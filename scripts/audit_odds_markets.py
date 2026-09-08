from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.ucl_2026 import FIXTURES
from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json

KEYWORDS = (
    "shot",
    "corner",
    "card",
    "foul",
    "offside",
    "goal",
    "handicap",
    "team total",
    "total",
    "head",
    "h2h",
)


def relevant(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in KEYWORDS)


def get_odds(client: APIFootballClient, fixture_id: int) -> list[dict[str, Any]]:
    key = f"fixture_{fixture_id}"
    cached = load_json("odds", key)
    if cached is not None:
        return cached
    rows = client.odds(fixture=fixture_id).response
    save_json("odds", key, rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit API-Football bookmaker markets for today's UCL fixtures."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print every returned market, not only stat-relevant names.",
    )
    args = parser.parse_args()

    client = APIFootballClient()
    output: dict[str, Any] = {"fixtures": {}}

    for fixture_id, fixture in FIXTURES.items():
        home = fixture["home"]["name"]
        away = fixture["away"]["name"]
        rows = get_odds(client, fixture_id)

        markets: dict[tuple[Any, str], dict[str, Any]] = {}
        for row in rows:
            for bookmaker in row.get("bookmakers", []):
                book_name = str(bookmaker.get("name") or bookmaker.get("id") or "Unknown")
                for bet in bookmaker.get("bets", []):
                    bet_id = bet.get("id")
                    bet_name = str(bet.get("name") or "")
                    key = (bet_id, bet_name)
                    entry = markets.setdefault(
                        key,
                        {
                            "bet_id": bet_id,
                            "name": bet_name,
                            "bookmakers": set(),
                            "sample_values": [],
                        },
                    )
                    entry["bookmakers"].add(book_name)
                    for value in bet.get("values", [])[:8]:
                        sample = {
                            "value": value.get("value"),
                            "odd": value.get("odd"),
                            "bookmaker": book_name,
                        }
                        if sample not in entry["sample_values"]:
                            entry["sample_values"].append(sample)

        print("=" * 100)
        print(f"{home} vs {away} | fixture {fixture_id}")

        selected = []
        for (_, _), entry in sorted(
            markets.items(), key=lambda kv: (str(kv[0][1]).lower(), str(kv[0][0]))
        ):
            if not args.all and not relevant(entry["name"]):
                continue
            selected.append(entry)
            print(
                f"  bet_id={entry['bet_id']} | {entry['name']} | "
                f"books={len(entry['bookmakers'])}"
            )
            for sample in entry["sample_values"][:5]:
                print(
                    f"    {sample['value']} @ {sample['odd']} "
                    f"({sample['bookmaker']})"
                )

        serializable = []
        for entry in selected:
            serializable.append(
                {
                    "bet_id": entry["bet_id"],
                    "name": entry["name"],
                    "bookmakers": sorted(entry["bookmakers"]),
                    "sample_values": entry["sample_values"][:20],
                }
            )
        output["fixtures"][str(fixture_id)] = {
            "home": home,
            "away": away,
            "markets": serializable,
        }

        if not selected:
            print("  No stat-relevant market names returned by API-Football.")

    path = save_json("odds_market_audit", "ucl_2026_09_08", output)
    print("\n" + "=" * 100)
    print(f"Saved market audit to {path}")


if __name__ == "__main__":
    main()

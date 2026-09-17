from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import save_json
from nfl.ingest.team_odds import TEAM_BET_MAP


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit current NFL team-stat betting markets."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    client = APINFLClient()
    rows = client.odds(args.game).response

    selected = []
    all_markets = []
    for row in rows:
        for book in row.get("bookmakers") or []:
            for bet in book.get("bets") or []:
                try:
                    all_bid = int(bet.get("id"))
                except (TypeError, ValueError):
                    all_bid = None
                all_markets.append(
                    {
                        "bookmaker": book.get("name") or book.get("id"),
                        "bet_id": all_bid,
                        "name": bet.get("name"),
                    }
                )
                try:
                    bid = int(bet.get("id"))
                except (TypeError, ValueError):
                    continue
                if args.all or bid in TEAM_BET_MAP:
                    selected.append(
                        {
                            "bookmaker": book.get("name") or book.get("id"),
                            "bet_id": bid,
                            "name": bet.get("name"),
                            "values": bet.get("values") or [],
                        }
                    )

    print(f"Current team-stat markets: {len(selected)}\n")
    print(json.dumps(selected, ensure_ascii=False, indent=2))

    if not selected:
        print("\nNo mapped team-stat markets are currently posted.")
        print("Current sportsbook market IDs/names:")
        seen = set()
        for item in all_markets:
            key = (item.get("bookmaker"), item.get("bet_id"), item.get("name"))
            if key in seen:
                continue
            seen.add(key)
            print(
                f"  {str(item.get('bookmaker')):18s} | "
                f"{str(item.get('bet_id')):>5s} | {item.get('name')}"
            )

    path = save_json(
        "audits",
        f"team_markets_game_{args.game}",
        {
            "selected": selected,
            "all_markets": all_markets,
            "raw_rows": len(rows),
        },
    )
    print(f"\nSaved team-market audit to {path}")


if __name__ == "__main__":
    main()

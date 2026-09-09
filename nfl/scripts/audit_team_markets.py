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
    for row in rows:
        for book in row.get("bookmakers") or []:
            for bet in book.get("bets") or []:
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

    path = save_json(
        "audits",
        f"team_markets_game_{args.game}",
        {"selected": selected, "raw_rows": len(rows)},
    )
    print(f"\nSaved team-market audit to {path}")


if __name__ == "__main__":
    main()

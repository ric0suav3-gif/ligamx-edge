from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import save_json
from nfl.ingest.odds import BET_STAT

FOCUS_BET_IDS = set(BET_STAT)


def compact(value: object, limit: int = 30000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def market_id(row: dict[str, Any]) -> int | None:
    value = row.get("id") or row.get("bet", {}).get("id")
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def market_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("bet", {}).get("name") or "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect live/current API-NFL odds for one game."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    client = APINFLClient()
    rows = client.odds(args.game).response

    print(f"Odds payload rows: {len(rows)}")
    print("=" * 100)

    selected = []
    for row in rows:
        # API-Sports may return bookmaker containers with nested bets, or
        # flattened bet rows depending on endpoint/provider evolution.
        bookmakers = row.get("bookmakers")
        if isinstance(bookmakers, list):
            for book in bookmakers:
                for bet in book.get("bets") or []:
                    bid = market_id(bet)
                    if args.all or bid in FOCUS_BET_IDS:
                        selected.append(
                            {
                                "bookmaker": book.get("name") or book.get("id"),
                                "bet_id": bid,
                                "name": market_name(bet),
                                "values": bet.get("values") or [],
                            }
                        )
        else:
            bid = market_id(row)
            if args.all or bid in FOCUS_BET_IDS:
                selected.append(row)

    if not selected:
        print(
            "No focus prop markets found in the current response. "
            "Run with --all to inspect every returned market."
        )
    else:
        print(compact(selected))

    path = save_json(
        "audits",
        f"current_odds_game_{args.game}",
        {"raw": rows, "selected": selected},
    )
    print(f"\nSaved current odds audit to {path}")


if __name__ == "__main__":
    main()

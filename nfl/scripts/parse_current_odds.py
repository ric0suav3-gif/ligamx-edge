from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import save_json
from nfl.ingest.odds import best_player_prop_quotes, parse_player_prop_quotes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize current API-Sports NFL player prop odds."
    )
    parser.add_argument("--game", required=True)
    args = parser.parse_args()

    client = APINFLClient()
    raw = client.odds(args.game).response
    quotes = best_player_prop_quotes(parse_player_prop_quotes(raw))

    print(f"Normalized player prop quotes: {len(quotes)}\n")
    for quote in quotes:
        print(
            f"{quote.player_name:24s} | "
            f"{quote.stat:26s} | "
            f"{quote.side.upper():5s} {quote.line:>6g} | "
            f"{quote.odd:.2f} | {quote.bookmaker} | bet_id={quote.bet_id}"
        )

    payload = {
        "game_id": str(args.game),
        "quotes": [quote.__dict__ for quote in quotes],
    }
    path = save_json("odds_normalized", f"game_{args.game}", payload)
    print(f"\nSaved normalized odds to {path}")


if __name__ == "__main__":
    main()

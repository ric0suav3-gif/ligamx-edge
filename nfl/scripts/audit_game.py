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


def compact(value: object, max_chars: int = 10000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated by audit script]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect raw team/player stats and odds for one API-NFL game."
    )
    parser.add_argument("--game", required=True)
    parser.add_argument(
        "--group",
        default=None,
        help="Optional player statistics group, e.g. passing/receiving/rushing.",
    )
    args = parser.parse_args()

    client = APINFLClient()
    game = client.games(id=args.game).response
    team_stats = client.team_game_statistics(args.game).response
    player_stats = client.player_game_statistics(
        args.game,
        group=args.group,
    ).response

    print("GAME")
    print("=" * 100)
    print(compact(game, 5000))
    print("\nTEAM STATS")
    print("=" * 100)
    print(compact(team_stats, 12000))
    print("\nPLAYER STATS")
    print("=" * 100)
    print(compact(player_stats, 20000))

    try:
        odds = client.odds(args.game).response
    except Exception as exc:
        odds = []
        print(f"\nODDS request failed/empty: {exc}")
    else:
        print("\nODDS")
        print("=" * 100)
        print(compact(odds, 12000))

    suffix = f"_{args.group.lower()}" if args.group else ""
    path = save_json(
        "audits",
        f"game_{args.game}{suffix}",
        {
            "game": game,
            "team_stats": team_stats,
            "player_stats": player_stats,
            "odds": odds,
        },
    )
    print(f"\nSaved raw game audit to {path}")


if __name__ == "__main__":
    main()

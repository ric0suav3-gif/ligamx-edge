from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import save_json

KEYWORDS = (
    "player",
    "pass",
    "passing",
    "completion",
    "attempt",
    "rush",
    "rushing",
    "receiv",
    "reception",
    "catch",
    "catch",
    "target",
    "yard",
    "touchdown",
    "interception",
    "sack",
    "quarterback",
    "running back",
    "receiver",
    "team total",
)


def relevant(name: str) -> bool:
    text = name.lower()
    return any(token in text for token in KEYWORDS)


def bet_id(row: dict[str, Any]) -> Any:
    return row.get("id") or row.get("bet", {}).get("id")


def bet_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("bet", {}).get("name") or "")


def main() -> None:
    client = APINFLClient()
    rows = client.odds_bets().response

    print(f"API-NFL odds catalogue: {len(rows)} bet types\n")
    print("STAT/PROP-LIKE MARKETS")
    print("=" * 90)

    selected = []
    for row in rows:
        name = bet_name(row)
        if relevant(name):
            selected.append(row)
            print(f"{str(bet_id(row)):>5} | {name}")

    print("\n" + "=" * 90)
    print(f"Relevant: {len(selected)} / {len(rows)}")
    if not selected:
        print(
            "No prop-like names matched our keyword filter. "
            "The full catalogue was still saved for inspection."
        )

    path = save_json(
        "audits",
        "odds_bets",
        {
            "all": rows,
            "relevant": selected,
        },
    )
    print(f"Saved catalogue to {path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from .api_football import APIFootballClient
from .cache import load_json, save_json


@dataclass(frozen=True)
class Price:
    outcome: str
    odd: float
    bookmaker: str


@dataclass(frozen=True)
class OneXTwoMarket:
    best: dict[str, Price]
    median_odds: dict[str, float]


OUTCOME_MAP = {
    "home": "home",
    "1": "home",
    "draw": "draw",
    "x": "draw",
    "away": "away",
    "2": "away",
}


def _normalize_outcome(value: Any) -> str | None:
    if value is None:
        return None
    return OUTCOME_MAP.get(str(value).strip().lower())


def _is_1x2(name: Any) -> bool:
    text = str(name or "").strip().lower()
    return text in {
        "match winner",
        "1x2",
        "fulltime result",
        "full time result",
        "winner",
    }


def parse_1x2(rows: list[dict[str, Any]]) -> OneXTwoMarket | None:
    prices: dict[str, list[Price]] = {"home": [], "draw": [], "away": []}

    for row in rows:
        for bookmaker in row.get("bookmakers", []):
            book_name = str(bookmaker.get("name") or bookmaker.get("id") or "Unknown")
            for bet in bookmaker.get("bets", []):
                if not _is_1x2(bet.get("name")):
                    continue
                for value in bet.get("values", []):
                    outcome = _normalize_outcome(value.get("value"))
                    if outcome is None:
                        continue
                    try:
                        odd = float(value.get("odd"))
                    except (TypeError, ValueError):
                        continue
                    if odd <= 1.0:
                        continue
                    prices[outcome].append(Price(outcome, odd, book_name))

    if not all(prices.values()):
        return None

    best = {
        outcome: max(items, key=lambda x: x.odd)
        for outcome, items in prices.items()
    }
    med = {
        outcome: median([item.odd for item in items])
        for outcome, items in prices.items()
    }
    return OneXTwoMarket(best=best, median_odds=med)


def fixture_1x2(
    client: APIFootballClient,
    fixture_id: int,
) -> OneXTwoMarket | None:
    key = f"fixture_{fixture_id}"
    cached = load_json("odds", key)
    if cached is None:
        cached = client.odds(fixture=fixture_id).response
        save_json("odds", key, cached)
    return parse_1x2(cached)

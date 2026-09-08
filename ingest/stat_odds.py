from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

BET_MAP = {
    45: ("corners", "match_total"),
    55: ("corners", "h2h"),
    56: ("corners", "handicap"),
    57: ("corners", "home_total"),
    58: ("corners", "away_total"),
    87: ("shots_on_target", "match_total"),
    176: ("shots_on_target", "h2h"),
    177: ("shots_on_target", "handicap"),
    211: ("shots", "match_total"),
    340: ("shots", "h2h"),
}

TOTAL_RE = re.compile(r"^(Over|Under)\s+(-?\d+(?:\.\d+)?)$", re.I)
HANDICAP_RE = re.compile(r"^(Home|Away)\s+([+-]?\d+(?:\.\d+)?)$", re.I)


@dataclass(frozen=True)
class StatQuote:
    stat: str
    market_type: str
    selection: str
    line: float | None
    odd: float
    bookmaker: str
    bet_id: int
    market_name: str


def _odd(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 1.0 else None


def parse_stat_quotes(rows: list[dict[str, Any]]) -> list[StatQuote]:
    """Parse the stat markets UCL Edge currently knows how to price."""
    quotes: list[StatQuote] = []

    for row in rows:
        for bookmaker in row.get("bookmakers", []):
            book = str(bookmaker.get("name") or bookmaker.get("id") or "Unknown")
            for bet in bookmaker.get("bets", []):
                try:
                    bet_id = int(bet.get("id"))
                except (TypeError, ValueError):
                    continue

                spec = BET_MAP.get(bet_id)
                if spec is None:
                    continue
                stat, market_type = spec
                market_name = str(bet.get("name") or "")

                for value in bet.get("values", []):
                    price = _odd(value.get("odd"))
                    if price is None:
                        continue
                    raw = str(value.get("value") or "").strip()

                    if market_type in {"match_total", "home_total", "away_total"}:
                        match = TOTAL_RE.match(raw)
                        if not match:
                            continue
                        selection = match.group(1).lower()
                        line = float(match.group(2))
                    elif market_type == "h2h":
                        selection = raw.lower()
                        if selection not in {"home", "draw", "away"}:
                            continue
                        line = None
                    elif market_type == "handicap":
                        match = HANDICAP_RE.match(raw)
                        if not match:
                            continue
                        selection = match.group(1).lower()
                        line = float(match.group(2))
                    else:
                        continue

                    quotes.append(
                        StatQuote(
                            stat=stat,
                            market_type=market_type,
                            selection=selection,
                            line=line,
                            odd=price,
                            bookmaker=book,
                            bet_id=bet_id,
                            market_name=market_name,
                        )
                    )

    return quotes


def best_stat_quotes(quotes: list[StatQuote]) -> list[StatQuote]:
    """Keep the best decimal price for every exact selection/line."""
    best: dict[tuple[str, str, str, float | None], StatQuote] = {}
    for quote in quotes:
        key = (quote.stat, quote.market_type, quote.selection, quote.line)
        current = best.get(key)
        if current is None or quote.odd > current.odd:
            best[key] = quote
    return sorted(
        best.values(),
        key=lambda q: (q.stat, q.market_type, q.line if q.line is not None else -999, q.selection),
    )

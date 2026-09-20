from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Canonical stat mapping from the API-Sports NFL odds catalogue we audited.
# Several markets are duplicated as generic/home/away provider families.
BET_STAT = {
    95: "interceptions",
    207: "passing_touchdowns",
    208: "passing_touchdowns",
    209: "passing_touchdowns",
    210: "passing_yards",
    211: "passing_yards",
    227: "completions",
    228: "completions",
    235: "passing_yards",
    236: "rushing_yards",
    237: "rushing_yards",
    238: "rushing_yards",
    242: "interceptions",
    244: "completions",
    254: "longest_reception",
    255: "longest_reception",
    256: "longest_reception",
    259: "rush_attempts",
    260: "rush_attempts",
    262: "longest_rush",
    263: "longest_rush",
    266: "receiving_yards",
    267: "receiving_yards",
    268: "receiving_yards",
    271: "rushing_receiving_yards",
    272: "rushing_receiving_yards",
    274: "longest_rush",
    282: "rushing_receiving_yards",
    290: "rush_attempts",
    295: "interceptions",
    302: "longest_pass_completion",
    326: "completions",
    327: "longest_reception",
    328: "rushing_yards",
    332: "rush_attempts",
    335: "passing_touchdowns",
    336: "passing_yards",
    342: "longest_pass_completion",
    345: "interceptions",
    346: "interceptions",
}

PROP_RE = re.compile(
    r"^(?P<player>.+?)\s+-\s+(?P<side>Over|Under)\s+"
    r"(?P<line>-?\d+(?:\.\d+)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlayerPropQuote:
    player_name: str
    stat: str
    side: str
    line: float
    odd: float
    bookmaker: str
    bet_id: int
    market_name: str


def _price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 1.0 else None


def _bet_id(row: dict[str, Any]) -> int | None:
    value = row.get("id") or row.get("bet", {}).get("id")
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _bet_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("bet", {}).get("name") or "")


def _parse_values(
    bet: dict[str, Any],
    bookmaker: str,
) -> list[PlayerPropQuote]:
    bid = _bet_id(bet)
    if bid is None or bid not in BET_STAT:
        return []

    stat = BET_STAT[bid]
    name = _bet_name(bet)
    out: list[PlayerPropQuote] = []

    for value in bet.get("values") or []:
        raw = str(value.get("value") or "").strip()
        match = PROP_RE.match(raw)
        if not match:
            continue
        odd = _price(value.get("odd"))
        if odd is None:
            continue

        out.append(
            PlayerPropQuote(
                player_name=match.group("player").strip(),
                stat=stat,
                side=match.group("side").lower(),
                line=float(match.group("line")),
                odd=odd,
                bookmaker=bookmaker,
                bet_id=bid,
                market_name=name,
            )
        )

    return out


def parse_player_prop_quotes(rows: list[dict[str, Any]]) -> list[PlayerPropQuote]:
    quotes: list[PlayerPropQuote] = []

    for row in rows:
        bookmakers = row.get("bookmakers")
        if isinstance(bookmakers, list):
            for book in bookmakers:
                bookmaker = str(book.get("name") or book.get("id") or "Unknown")
                for bet in book.get("bets") or []:
                    quotes.extend(_parse_values(bet, bookmaker))
            continue

        # Also support the flattened audit representation:
        # {bookmaker, bet_id, name, values}.
        bookmaker = str(row.get("bookmaker") or "Unknown")
        flat_bet = {
            "id": row.get("bet_id") or row.get("id"),
            "name": row.get("name"),
            "values": row.get("values") or [],
        }
        quotes.extend(_parse_values(flat_bet, bookmaker))

    return quotes


def best_player_prop_quotes(
    quotes: list[PlayerPropQuote],
) -> list[PlayerPropQuote]:
    best: dict[tuple[str, str, str, float], PlayerPropQuote] = {}

    for quote in quotes:
        key = (
            quote.player_name.lower(),
            quote.stat,
            quote.side,
            quote.line,
        )
        current = best.get(key)
        if current is None or quote.odd > current.odd:
            best[key] = quote

    return sorted(
        best.values(),
        key=lambda q: (
            q.player_name.lower(),
            q.stat,
            q.line,
            q.side,
        ),
    )

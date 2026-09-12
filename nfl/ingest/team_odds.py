from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeamMarketSpec:
    stat: str
    scope: str  # home_total, away_total, match_total


# Confirmed from the API-NFL catalogue audit. Settlement semantics for passing
# yards should still be audited against a live sportsbook payload before release.
TEAM_BET_MAP = {
    # Generic NFL scoreboard totals. The live 2026-09-09 audit confirmed
    # these are actively posted across Marathon/Pinnacle/1xBet.
    3: TeamMarketSpec("points", "match_total"),
    8: TeamMarketSpec("points", "home_total"),
    9: TeamMarketSpec("points", "away_total"),
    216: TeamMarketSpec("pass_attempts", "match_total"),
    217: TeamMarketSpec("pass_completions", "match_total"),
    219: TeamMarketSpec("passing_yards", "match_total"),
    232: TeamMarketSpec("rushing_yards", "match_total"),
    233: TeamMarketSpec("rushing_yards", "home_total"),
    234: TeamMarketSpec("rushing_yards", "away_total"),
    286: TeamMarketSpec("sacks", "home_total"),
    287: TeamMarketSpec("rush_attempts", "home_total"),
    288: TeamMarketSpec("rush_attempts", "away_total"),
    289: TeamMarketSpec("rush_attempts", "match_total"),
    298: TeamMarketSpec("sacks", "away_total"),
    319: TeamMarketSpec("sacks", "match_total"),
    355: TeamMarketSpec("rush_attempts", "match_total"),
    356: TeamMarketSpec("passing_touchdowns", "match_total"),
    357: TeamMarketSpec("rushing_yards", "match_total"),
}

OU_RE = re.compile(
    r"^(?P<side>Over|Under)\s+(?P<line>-?\d+(?:\.\d+)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TeamPropQuote:
    stat: str
    scope: str
    side: str
    line: float
    odd: float
    bookmaker: str
    bet_id: int
    market_name: str


def _id(row: dict[str, Any]) -> int | None:
    value = row.get("id") or row.get("bet", {}).get("id")
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("bet", {}).get("name") or "")


def parse_team_prop_quotes(rows: list[dict[str, Any]]) -> list[TeamPropQuote]:
    out: list[TeamPropQuote] = []

    for row in rows:
        books = row.get("bookmakers")
        if not isinstance(books, list):
            books = [
                {
                    "name": row.get("bookmaker") or "Unknown",
                    "bets": [
                        {
                            "id": row.get("bet_id") or row.get("id"),
                            "name": row.get("name"),
                            "values": row.get("values") or [],
                        }
                    ],
                }
            ]

        for book in books:
            bookmaker = str(book.get("name") or book.get("id") or "Unknown")
            for bet in book.get("bets") or []:
                bid = _id(bet)
                spec = TEAM_BET_MAP.get(bid or -1)
                if spec is None:
                    continue
                for value in bet.get("values") or []:
                    raw = str(value.get("value") or "").strip()
                    match = OU_RE.match(raw)
                    if not match:
                        continue
                    try:
                        odd = float(value.get("odd"))
                    except (TypeError, ValueError):
                        continue
                    if odd <= 1.0:
                        continue
                    out.append(
                        TeamPropQuote(
                            stat=spec.stat,
                            scope=spec.scope,
                            side=match.group("side").lower(),
                            line=float(match.group("line")),
                            odd=odd,
                            bookmaker=bookmaker,
                            bet_id=bid,
                            market_name=_name(bet),
                        )
                    )
    return out

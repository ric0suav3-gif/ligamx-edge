from __future__ import annotations

from itertools import combinations
from typing import Any


STRAIGHT_MIN_PRICE = 1.60
STRAIGHT_MAX_PRICE = 1.80
STRAIGHT_MIN_PROBABILITY = 0.62
STRAIGHT_MIN_EV = 0.05
STRAIGHT_MIN_BOOKS = 3
# Early results show that full-game totals are more stable than allocating the
# same projected points to one team. Keep the raw model probability for
# reporting, but use a small conservative haircut when selecting team totals.
TEAM_TOTAL_PROBABILITY_HAIRCUT = 0.03

PARLAY_LEG_MIN_PRICE = 1.15
PARLAY_LEG_MAX_PRICE = 1.50
PARLAY_LEG_MIN_PROBABILITY = 0.75
PARLAY_LEG_MIN_EV = 0.02
PARLAY_MIN_PRICE = 1.60
PARLAY_MAX_PRICE = 1.80


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _probability(row: dict[str, Any]) -> float:
    fair = _number(row.get("fair"))
    return 0.0 if fair <= 1.0 else 1.0 / fair


def _selection_probability(row: dict[str, Any]) -> float:
    probability = _probability(row)
    if str(row.get("scope")) in {"home_total", "away_total"}:
        probability -= TEAM_TOTAL_PROBABILITY_HAIRCUT
    return max(0.0, probability)


def _annotate(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "selection_probability": _selection_probability(row)}


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the safest qualifying alternate line for each market family."""
    best: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("game_id")),
            str(row.get("stat")),
            str(row.get("scope")),
            str(row.get("side")),
        )
        current = best.get(key)
        rank = (_selection_probability(row), _number(row.get("consensus_ev")))
        if current is None or rank > (
            _selection_probability(current),
            _number(current.get("consensus_ev")),
        ):
            best[key] = row
    return list(best.values())


def select_straights(
    rows: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return high-confidence straight bets, with at most one per game."""
    qualified = [
        row
        for row in rows
        if STRAIGHT_MIN_PRICE <= _number(row.get("median_odd")) <= STRAIGHT_MAX_PRICE
        and _selection_probability(row) >= STRAIGHT_MIN_PROBABILITY
        and _number(row.get("consensus_ev")) >= STRAIGHT_MIN_EV
        and int(row.get("books") or 0) >= STRAIGHT_MIN_BOOKS
    ]
    qualified = _dedupe(qualified)
    qualified.sort(
        key=lambda row: (
            _selection_probability(row),
            _number(row.get("consensus_ev")),
            int(row.get("books") or 0),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    used_games: set[str] = set()
    for row in qualified:
        game_id = str(row.get("game_id"))
        if game_id in used_games:
            continue
        selected.append(_annotate(row))
        used_games.add(game_id)
        if len(selected) >= limit:
            break
    return selected


def select_two_leg_parlays(
    rows: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Build conservative two-game parlays in the requested total price band."""
    legs = [
        row
        for row in rows
        if PARLAY_LEG_MIN_PRICE <= _number(row.get("median_odd")) <= PARLAY_LEG_MAX_PRICE
        and _selection_probability(row) >= PARLAY_LEG_MIN_PROBABILITY
        and _number(row.get("consensus_ev")) >= PARLAY_LEG_MIN_EV
        and int(row.get("books") or 0) >= STRAIGHT_MIN_BOOKS
    ]
    legs = _dedupe(legs)
    candidates: list[dict[str, Any]] = []
    for first, second in combinations(legs, 2):
        if str(first.get("game_id")) == str(second.get("game_id")):
            continue
        price = _number(first.get("median_odd")) * _number(second.get("median_odd"))
        if not PARLAY_MIN_PRICE <= price <= PARLAY_MAX_PRICE:
            continue
        probability = _selection_probability(first) * _selection_probability(second)
        candidates.append(
            {
                "legs": [_annotate(first), _annotate(second)],
                "price": price,
                "probability": probability,
                "fair": 1.0 / probability,
                "edge": probability * price - 1.0,
            }
        )

    candidates.sort(
        key=lambda row: (row["probability"], row["edge"]),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    used_pairs: set[frozenset[str]] = set()
    for row in candidates:
        pair = frozenset(str(leg.get("game_id")) for leg in row["legs"])
        if pair in used_pairs:
            continue
        selected.append(row)
        used_pairs.add(pair)
        if len(selected) >= limit:
            break
    return selected

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class GoalProjection:
    home_xg: float
    away_xg: float
    home_samples: int
    away_samples: int


def poisson_distribution(mean: float, max_goals: int = 12) -> list[float]:
    """Return a normalized Poisson distribution, including a small tail bucket."""
    mean = max(0.05, float(mean))
    values = [math.exp(-mean) * mean**k / math.factorial(k) for k in range(max_goals + 1)]
    values[-1] += max(0.0, 1.0 - sum(values))
    total = sum(values)
    return [value / total for value in values]


def match_probabilities(home_xg: float, away_xg: float) -> dict[str, float]:
    home = poisson_distribution(home_xg)
    away = poisson_distribution(away_xg)
    out = {
        "HOME": 0.0,
        "DRAW": 0.0,
        "AWAY": 0.0,
        "OVER_2_5": 0.0,
        "UNDER_2_5": 0.0,
        "BTTS_YES": 0.0,
        "BTTS_NO": 0.0,
    }
    for home_goals, p_home in enumerate(home):
        for away_goals, p_away in enumerate(away):
            probability = p_home * p_away
            if home_goals > away_goals:
                out["HOME"] += probability
            elif home_goals == away_goals:
                out["DRAW"] += probability
            else:
                out["AWAY"] += probability
            if home_goals + away_goals > 2:
                out["OVER_2_5"] += probability
            else:
                out["UNDER_2_5"] += probability
            if home_goals > 0 and away_goals > 0:
                out["BTTS_YES"] += probability
            else:
                out["BTTS_NO"] += probability
    return out


def exponential_mean(values: Sequence[float], half_life: float = 4.0) -> float:
    """Exponentially weighted mean for values ordered oldest to newest."""
    if not values:
        raise ValueError("values must not be empty")
    decay = math.log(2.0) / max(float(half_life), 0.1)
    raw_weights = [math.exp(-decay * age) for age in range(len(values) - 1, -1, -1)]
    total = sum(raw_weights)
    return sum(float(value) * weight for value, weight in zip(values, raw_weights)) / total


def project_goals(
    home_history: Sequence[tuple[float, float]],
    away_history: Sequence[tuple[float, float]],
    *,
    baseline_goals: float = 1.32,
    prior_matches: float = 7.0,
    home_advantage: float = 1.08,
) -> GoalProjection:
    """Project goals from recent API results with an intentionally strong prior.

    Each history item is ``(goals_for, goals_against)`` and must be ordered
    oldest to newest. National-team samples are noisy, so recent rates are
    shrunk heavily toward the slate scoring baseline.
    """
    if not home_history or not away_history:
        raise ValueError("both teams require at least one completed match")

    def shrunk(history: Sequence[tuple[float, float]]) -> tuple[float, float]:
        goals_for = exponential_mean([row[0] for row in history])
        goals_against = exponential_mean([row[1] for row in history])
        n = min(len(history), 12)
        attack = (n * goals_for + prior_matches * baseline_goals) / (n + prior_matches)
        defence = (n * goals_against + prior_matches * baseline_goals) / (n + prior_matches)
        return attack, defence

    home_attack, home_defence = shrunk(home_history)
    away_attack, away_defence = shrunk(away_history)
    home_xg = math.sqrt(max(home_attack * away_defence, 0.01)) * home_advantage
    away_xg = math.sqrt(max(away_attack * home_defence, 0.01)) / home_advantage
    return GoalProjection(
        home_xg=min(max(home_xg, 0.35), 3.40),
        away_xg=min(max(away_xg, 0.30), 3.20),
        home_samples=len(home_history),
        away_samples=len(away_history),
    )


def devig(prices: Mapping[str, float]) -> dict[str, float]:
    inverse = {name: 1.0 / float(price) for name, price in prices.items() if float(price) > 1.0}
    total = sum(inverse.values())
    if total <= 0 or len(inverse) != len(prices):
        raise ValueError("all decimal prices must be greater than 1.0")
    return {name: value / total for name, value in inverse.items()}


def consensus(probabilities: Iterable[float]) -> tuple[float, float]:
    values = [float(value) for value in probabilities]
    if not values:
        raise ValueError("at least one probability is required")
    spread = statistics.pstdev(values) if len(values) > 1 else 0.0
    return float(statistics.median(values)), spread


def blend_probabilities(
    market: Mapping[str, float],
    model: Mapping[str, float],
    api: Mapping[str, float] | None = None,
    *,
    market_weight: float = 0.75,
    model_weight: float = 0.20,
    api_weight: float = 0.05,
) -> dict[str, float]:
    """Shrink independent estimates toward a de-vigged market consensus."""
    api = api or {}
    keys = set(market) & set(model)
    if not keys:
        raise ValueError("market and model must share outcomes")
    use_api = bool(keys & set(api)) and api_weight > 0
    effective_api_weight = api_weight if use_api else 0.0
    total_weight = market_weight + model_weight + effective_api_weight
    mixed = {
        key: (
            market_weight * market[key]
            + model_weight * model[key]
            + effective_api_weight * api.get(key, model[key])
        )
        / total_weight
        for key in keys
    }
    total = sum(mixed.values())
    return {key: value / total for key, value in mixed.items()}


def expected_value(probability: float, decimal_odds: float) -> float:
    return float(probability) * float(decimal_odds) - 1.0


def grade_pick(edge: float, books: int, disagreement: float) -> str:
    if edge >= 0.07 and books >= 7 and disagreement <= 0.035:
        return "A"
    if edge >= 0.04 and books >= 5 and disagreement <= 0.055:
        return "B"
    return "C"


def settle(market: str, selection: str, home_goals: int, away_goals: int) -> str:
    if market == "1X2":
        winner = "HOME" if home_goals > away_goals else "AWAY" if away_goals > home_goals else "DRAW"
        return "WIN" if selection == winner else "LOSS"
    if market == "TOTAL_2_5":
        total = home_goals + away_goals
        winner = "OVER_2_5" if total > 2.5 else "UNDER_2_5"
        return "WIN" if selection == winner else "LOSS"
    if market == "BTTS":
        winner = "BTTS_YES" if home_goals > 0 and away_goals > 0 else "BTTS_NO"
        return "WIN" if selection == winner else "LOSS"
    raise ValueError(f"unsupported market: {market}")

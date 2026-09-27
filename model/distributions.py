from __future__ import annotations

import math
from dataclasses import dataclass


def poisson_pmf(k: int, mean: float) -> float:
    if mean <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(mean) - mean - math.lgamma(k + 1))


def negative_binomial_pmf(k: int, mean: float, r: float) -> float:
    if mean <= 0:
        return 1.0 if k == 0 else 0.0
    if r <= 0:
        raise ValueError("r must be positive")
    p = r / (r + mean)
    return math.exp(
        math.lgamma(k + r)
        - math.lgamma(r)
        - math.lgamma(k + 1)
        + r * math.log(p)
        + k * math.log(1 - p)
    )


def count_distribution(
    mean: float,
    r: float | None = None,
    tail_sd: float = 8.0,
) -> list[float]:
    variance = mean if r is None else mean + mean * mean / r
    sd = math.sqrt(max(variance, 0.0))
    max_k = max(10, math.ceil(mean + tail_sd * sd))

    if r is None:
        values = [poisson_pmf(k, mean) for k in range(max_k + 1)]
    else:
        values = [
            negative_binomial_pmf(k, mean, r) for k in range(max_k + 1)
        ]

    total = sum(values)
    return [v / total for v in values]


def convolve(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, p_a in enumerate(a):
        for j, p_b in enumerate(b):
            out[i + j] += p_a * p_b
    return out


@dataclass(frozen=True)
class OneXTwo:
    home: float
    draw: float
    away: float

    @property
    def fair_home(self) -> float:
        return 1.0 / self.home

    @property
    def fair_draw(self) -> float:
        return 1.0 / self.draw

    @property
    def fair_away(self) -> float:
        return 1.0 / self.away


def one_x_two_from_goals(home_mean: float, away_mean: float) -> OneXTwo:
    home = count_distribution(home_mean)
    away = count_distribution(away_mean)

    p_home = 0.0
    p_draw = 0.0
    p_away = 0.0

    for h, p_h in enumerate(home):
        for a, p_a in enumerate(away):
            p = p_h * p_a
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p

    total = p_home + p_draw + p_away
    return OneXTwo(p_home / total, p_draw / total, p_away / total)

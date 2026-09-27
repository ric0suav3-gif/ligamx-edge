from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, variance
from typing import Iterable


@dataclass(frozen=True)
class CountFit:
    mean: float
    variance: float
    r: float | None
    family: str


@dataclass(frozen=True)
class FairPrice:
    win: float
    push: float
    loss: float
    fair_odds: float | None


def fit_count_distribution(values: Iterable[float | int | None]) -> CountFit:
    clean = [float(x) for x in values if x is not None]
    if not clean:
        raise ValueError("No count observations")
    mu = mean(clean)
    var = variance(clean) if len(clean) >= 2 else mu
    if mu <= 0 or var <= mu * 1.05:
        return CountFit(mu, var, None, "poisson")
    r = (mu * mu) / max(1e-12, var - mu)
    return CountFit(mu, var, r, "negative_binomial")


def _poisson_pmf(k: int, mu: float) -> float:
    if k < 0:
        return 0.0
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-mu + k * math.log(mu) - math.lgamma(k + 1))


def _nb_pmf(k: int, mu: float, r: float) -> float:
    if k < 0:
        return 0.0
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    if r <= 0:
        raise ValueError("r must be positive")
    p = r / (r + mu)
    return math.exp(
        math.lgamma(k + r)
        - math.lgamma(r)
        - math.lgamma(k + 1)
        + r * math.log(p)
        + k * math.log1p(-p)
    )


def count_pmf(k: int, mu: float, r: float | None) -> float:
    return _poisson_pmf(k, mu) if r is None else _nb_pmf(k, mu, r)


def count_fair_price(
    mu: float,
    line: float,
    side: str,
    r: float | None = None,
    max_k: int | None = None,
) -> FairPrice:
    if side not in {"over", "under"}:
        raise ValueError("side must be over or under")
    if mu < 0:
        raise ValueError("mean must be non-negative")

    cap = max_k or max(40, int(math.ceil(mu + 12.0 * math.sqrt(mu + mu * mu / (r or 1e12)))))
    probs = [count_pmf(k, mu, r) for k in range(cap + 1)]
    total = sum(probs)
    if total <= 0:
        raise ValueError("invalid count distribution")
    probs = [p / total for p in probs]

    win = push = loss = 0.0
    for k, p in enumerate(probs):
        if abs(k - line) < 1e-12:
            push += p
        elif (side == "over" and k > line) or (side == "under" and k < line):
            win += p
        else:
            loss += p

    fair = None if win <= 0 else 1.0 + loss / win
    return FairPrice(win=win, push=push, loss=loss, fair_odds=fair)


def normal_cdf(x: float, mu: float, sigma: float) -> float:
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    z = (x - mu) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def normal_fair_price(
    mu: float,
    sigma: float,
    line: float,
    side: str,
) -> FairPrice:
    if side not in {"over", "under"}:
        raise ValueError("side must be over or under")
    p_under = normal_cdf(line, mu, sigma)
    win = 1.0 - p_under if side == "over" else p_under
    loss = 1.0 - win
    fair = None if win <= 0 else 1.0 / win
    return FairPrice(win=win, push=0.0, loss=loss, fair_odds=fair)

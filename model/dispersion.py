from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, variance


@dataclass(frozen=True)
class CountFit:
    n: int
    mean: float | None
    variance: float | None
    r: float | None
    family: str


def fit_count_distribution(values: list[float]) -> CountFit:
    """Method-of-moments Poisson / negative-binomial fit.

    If sample variance is not meaningfully above the mean, use Poisson
    (r=None). Otherwise NB variance = mean + mean^2 / r.
    """
    clean = [float(v) for v in values if v is not None]
    n = len(clean)
    if n == 0:
        return CountFit(0, None, None, None, "missing")

    mean = fmean(clean)
    var = variance(clean) if n >= 2 else mean

    if mean <= 0 or var <= mean * 1.02:
        return CountFit(n, mean, var, None, "poisson")

    r = mean * mean / (var - mean)
    return CountFit(n, mean, var, r, "negative_binomial")

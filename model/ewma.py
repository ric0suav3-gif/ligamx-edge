from __future__ import annotations

import math
from collections.abc import Iterable


def recency_weights(n: int, half_life: float) -> list[float]:
    """Return normalized oldest->newest exponential weights."""
    if n <= 0:
        return []
    if half_life <= 0:
        raise ValueError("half_life must be positive")

    decay = math.log(2.0) / half_life
    raw = [math.exp(-decay * age) for age in range(n - 1, -1, -1)]
    total = sum(raw)
    return [x / total for x in raw]


def ewma(values: Iterable[float | None], half_life: float = 25.0) -> float | None:
    """Exponentially weighted mean, ignoring missing observations.

    Input order must be oldest -> newest. Missing values do not become zero.
    """
    clean = [v for v in values if v is not None]
    if not clean:
        return None

    weights = recency_weights(len(clean), half_life)
    return sum(float(v) * w for v, w in zip(clean, weights))

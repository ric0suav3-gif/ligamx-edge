from __future__ import annotations

import math
from typing import Iterable


def recency_weights(n: int, half_life: float) -> list[float]:
    if n <= 0:
        return []
    if half_life <= 0:
        raise ValueError("half_life must be > 0")
    decay = math.log(2.0) / half_life
    return [math.exp(-decay * (n - 1 - i)) for i in range(n)]


def ewma(values: Iterable[float | int | None], half_life: float = 8.0) -> float | None:
    clean = [(idx, float(v)) for idx, v in enumerate(values) if v is not None]
    if not clean:
        return None
    n = len(list(values)) if not isinstance(values, list) else len(values)
    weights = recency_weights(n, half_life)
    num = sum(weights[idx] * value for idx, value in clean)
    den = sum(weights[idx] for idx, _ in clean)
    return None if den <= 0 else num / den

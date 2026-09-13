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
    seq = list(values)
    if not seq:
        return None
    weights = recency_weights(len(seq), half_life)
    clean = [
        (idx, float(value))
        for idx, value in enumerate(seq)
        if value is not None
    ]
    if not clean:
        return None
    numerator = sum(weights[idx] * value for idx, value in clean)
    denominator = sum(weights[idx] for idx, _ in clean)
    return None if denominator <= 0 else numerator / denominator

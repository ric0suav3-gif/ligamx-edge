from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class RegressionMetrics:
    n: int
    mae: float
    rmse: float
    bias: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "mae": self.mae,
            "rmse": self.rmse,
            "bias": self.bias,
        }


def regression_metrics(
    predicted: Iterable[float],
    actual: Iterable[float],
) -> RegressionMetrics:
    pairs = [
        (float(p), float(a))
        for p, a in zip(predicted, actual)
        if p is not None and a is not None
    ]
    if not pairs:
        raise ValueError("No prediction/actual pairs")

    errors = [p - a for p, a in pairs]
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    bias = sum(errors) / n
    return RegressionMetrics(n=n, mae=mae, rmse=rmse, bias=bias)

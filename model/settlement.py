from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settlement:
    result: str
    win_stake: float
    push_stake: float
    loss_stake: float


def split_asian_line(line: float) -> tuple[float, ...]:
    """Split a quarter Asian line into its two half-stake component lines.

    Examples:
      2.25 -> (2.0, 2.5)
      2.75 -> (2.5, 3.0)
      -1.25 -> (-1.5, -1.0)

    Integer and half lines remain single-line markets.
    """
    q = round(float(line) * 4)
    if abs(float(line) * 4 - q) > 1e-8:
        raise ValueError(f"Asian line must be in 0.25 increments: {line}")

    # Odd quarter count means .25/.75 (including negative lines).
    if abs(q) % 2 == 1:
        return (float(line) - 0.25, float(line) + 0.25)
    return (float(line),)


def _component(value: float) -> str:
    if value > 1e-9:
        return "W"
    if value < -1e-9:
        return "L"
    return "P"


def _combine(parts: list[str]) -> Settlement:
    n = float(len(parts))
    wins = sum(x == "W" for x in parts) / n
    pushes = sum(x == "P" for x in parts) / n
    losses = sum(x == "L" for x in parts) / n

    if wins == 1.0:
        result = "W"
    elif losses == 1.0:
        result = "L"
    elif pushes == 1.0:
        result = "P"
    elif wins > 0 and pushes > 0:
        result = "HW"
    elif losses > 0 and pushes > 0:
        result = "HL"
    else:
        # Defensive fallback for unusual component combinations.
        result = "MIXED"

    return Settlement(result, wins, pushes, losses)


def settle_total(actual: float, selection: str, line: float) -> Settlement:
    side = selection.lower().strip()
    if side not in {"over", "under"}:
        raise ValueError(f"Unsupported total selection: {selection}")

    parts: list[str] = []
    for component_line in split_asian_line(line):
        delta = float(actual) - component_line
        if side == "under":
            delta = -delta
        parts.append(_component(delta))
    return _combine(parts)


def settle_handicap(
    selected_actual: float,
    opponent_actual: float,
    handicap: float,
) -> Settlement:
    margin = float(selected_actual) - float(opponent_actual)
    parts = [
        _component(margin + component_line)
        for component_line in split_asian_line(handicap)
    ]
    return _combine(parts)


def pnl_for_settlement(settlement: Settlement, decimal_odds: float | None) -> float | None:
    """Return profit/loss for one unit staked at decimal odds."""
    if decimal_odds is None:
        return None
    odd = float(decimal_odds)
    if odd <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0: {decimal_odds}")
    return settlement.win_stake * (odd - 1.0) - settlement.loss_stake

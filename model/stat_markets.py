from __future__ import annotations

from dataclasses import dataclass

from .distributions import convolve, count_distribution


@dataclass(frozen=True)
class AsianFair:
    win_equivalent: float
    loss_equivalent: float
    push: float
    fair_odds: float | None


@dataclass(frozen=True)
class H2HFair:
    first_win: float
    tie: float
    second_win: float
    fair_first: float | None
    fair_second: float | None


def _split_asian_line(line: float) -> list[tuple[float, float]]:
    """Return (component_line, stake_weight) for Asian quarter lines."""
    q = round(line * 4)
    if q % 2 == 0:
        return [(line, 1.0)]
    return [(line - 0.25, 0.5), (line + 0.25, 0.5)]


def _fair_from_equivalents(win_eq: float, loss_eq: float, push: float) -> AsianFair:
    fair = None if win_eq <= 1e-12 else 1.0 + loss_eq / win_eq
    return AsianFair(
        win_equivalent=win_eq,
        loss_equivalent=loss_eq,
        push=push,
        fair_odds=fair,
    )


def asian_team_total(
    mean: float,
    line: float,
    side: str,
    dispersion_r: float | None = None,
) -> AsianFair:
    """Fair price for an Asian over/under team total.

    Quarter lines are settled as two half-stakes on adjacent half-unit lines.
    Integer lines can push. Supports any count stat once a mean and dispersion
    are supplied.
    """
    if side not in {"over", "under"}:
        raise ValueError("side must be 'over' or 'under'")

    dist = count_distribution(mean, dispersion_r)
    components = _split_asian_line(line)
    win_eq = loss_eq = push = 0.0

    for k, prob in enumerate(dist):
        for component, weight in components:
            delta = k - component
            if side == "under":
                delta = -delta
            if delta > 1e-12:
                win_eq += prob * weight
            elif delta < -1e-12:
                loss_eq += prob * weight
            else:
                push += prob * weight

    return _fair_from_equivalents(win_eq, loss_eq, push)


def margin_distribution(
    first_mean: float,
    second_mean: float,
    first_r: float | None = None,
    second_r: float | None = None,
) -> tuple[list[float], int]:
    first = count_distribution(first_mean, first_r)
    second = count_distribution(second_mean, second_r)
    n = max(len(first), len(second))
    off = n - 1
    margin = [0.0] * (2 * n - 1)

    for i, p_first in enumerate(first):
        for j, p_second in enumerate(second):
            margin[i - j + off] += p_first * p_second

    total = sum(margin)
    return [p / total for p in margin], off


def asian_handicap(
    first_mean: float,
    second_mean: float,
    line: float,
    first_r: float | None = None,
    second_r: float | None = None,
) -> AsianFair:
    """Fair price for the first side at the supplied Asian handicap."""
    margin, off = margin_distribution(first_mean, second_mean, first_r, second_r)
    components = _split_asian_line(line)
    win_eq = loss_eq = push = 0.0

    for idx, prob in enumerate(margin):
        raw_margin = idx - off
        for component, weight in components:
            settled = raw_margin + component
            if settled > 1e-12:
                win_eq += prob * weight
            elif settled < -1e-12:
                loss_eq += prob * weight
            else:
                push += prob * weight

    return _fair_from_equivalents(win_eq, loss_eq, push)


def h2h(
    first_mean: float,
    second_mean: float,
    first_r: float | None = None,
    second_r: float | None = None,
) -> H2HFair:
    """H2H count market where a tie is treated as a push."""
    margin, off = margin_distribution(first_mean, second_mean, first_r, second_r)
    first = tie = second = 0.0

    for idx, prob in enumerate(margin):
        m = idx - off
        if m > 0:
            first += prob
        elif m < 0:
            second += prob
        else:
            tie += prob

    fair_first = None if first <= 1e-12 else (1.0 - tie) / first
    fair_second = None if second <= 1e-12 else (1.0 - tie) / second
    return H2HFair(first, tie, second, fair_first, fair_second)


def asian_match_total(
    first_mean: float,
    second_mean: float,
    line: float,
    side: str,
    first_r: float | None = None,
    second_r: float | None = None,
) -> AsianFair:
    """Asian total for combined team counts."""
    if side not in {"over", "under"}:
        raise ValueError("side must be 'over' or 'under'")

    total = convolve(
        count_distribution(first_mean, first_r),
        count_distribution(second_mean, second_r),
    )
    components = _split_asian_line(line)
    win_eq = loss_eq = push = 0.0

    for k, prob in enumerate(total):
        for component, weight in components:
            delta = k - component
            if side == "under":
                delta = -delta
            if delta > 1e-12:
                win_eq += prob * weight
            elif delta < -1e-12:
                loss_eq += prob * weight
            else:
                push += prob * weight

    return _fair_from_equivalents(win_eq, loss_eq, push)

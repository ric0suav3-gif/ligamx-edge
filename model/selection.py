from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionGrade:
    band: str
    score: float
    flags: tuple[str, ...]


def fair_band(fair_odds: float) -> str:
    """Risk band used for straight-pick selection.

    CORE intentionally mirrors the practical fair-price zone used by the
    Liga MX UI: enough payout to matter without letting low-probability
    longshots dominate a ranking purely because their quoted EV is large.
    """
    fair = float(fair_odds)
    if 1.45 <= fair <= 2.50:
        return "CORE"
    if 1.25 <= fair <= 3.25:
        return "EXTENDED"
    return "LONGSHOT"


def balanced_score(
    *,
    fair_odds: float,
    consensus_ev: float,
    books: int,
    reliability: str,
    market_type: str,
    source: str,
) -> SelectionGrade:
    """Risk-adjusted score for choosing a practical straight from a fixture.

    This is a *selection* layer, not a change to the underlying model fair
    price. Raw EV is deliberately capped in the score so a 15-20% hit-rate
    longshot cannot automatically outrank a solid 50-65% market. The raw EV
    is still stored and displayed separately.
    """
    fair = max(float(fair_odds), 1.000001)
    ev = float(consensus_ev)
    n_books = max(int(books), 0)
    rel = str(reliability or "UNKNOWN").upper()
    kind = str(market_type or "")
    src = str(source or "")

    band = fair_band(fair)
    decision_p = 1.0 / fair

    # Cap EV contribution. Extreme model-vs-book disagreements remain visible
    # as flags but cannot dominate the recommendation engine by themselves.
    ev_component = max(-0.25, min(ev, 0.50)) * 0.55
    probability_component = (decision_p - 0.50) * 0.18
    book_component = min(n_books, 5) * 0.004

    if band == "CORE":
        band_component = 0.18
    elif band == "EXTENDED":
        band_component = 0.07
    else:
        band_component = -0.20

    reliability_component = {
        "HIGH": 0.050,
        "MEDIUM": 0.025,
        "LOW": -0.030,
        "UNKNOWN": -0.015,
    }.get(rel, -0.015)

    # Team totals are univariate in the current UCL model. Joint markets are
    # useful, but they still assume independence until covariance calibration.
    joint_component = -0.035 if kind in {"match_total", "handicap", "h2h"} else 0.0
    fallback_component = -0.080 if src == "ONE_SIDED_FALLBACK" else 0.0

    flags: list[str] = []
    if band == "LONGSHOT":
        flags.append("LONGSHOT")
    if ev >= 0.50:
        flags.append("EXTREME_EV")
    if kind in {"match_total", "handicap", "h2h"}:
        flags.append("JOINT_INDEPENDENCE")
    if src == "ONE_SIDED_FALLBACK":
        flags.append("ONE_SIDED_PROXY")
    if rel == "LOW":
        flags.append("LOW_RELIABILITY")

    score = (
        ev_component
        + probability_component
        + book_component
        + band_component
        + reliability_component
        + joint_component
        + fallback_component
    )
    return SelectionGrade(band=band, score=score, flags=tuple(flags))

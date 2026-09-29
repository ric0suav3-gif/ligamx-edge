from __future__ import annotations

import math

from today_edge.model import (
    blend_probabilities,
    devig,
    expected_value,
    match_probabilities,
    project_goals,
    settle,
)


def test_match_probabilities_are_normalized() -> None:
    probabilities = match_probabilities(1.6, 1.1)
    assert math.isclose(
        probabilities["HOME"] + probabilities["DRAW"] + probabilities["AWAY"],
        1.0,
        abs_tol=1e-9,
    )
    assert math.isclose(
        probabilities["OVER_2_5"] + probabilities["UNDER_2_5"],
        1.0,
        abs_tol=1e-9,
    )
    assert math.isclose(
        probabilities["BTTS_YES"] + probabilities["BTTS_NO"],
        1.0,
        abs_tol=1e-9,
    )


def test_project_goals_shrinks_extreme_recent_form() -> None:
    projection = project_goals([(5, 0)] * 6, [(0, 5)] * 6)
    assert projection.home_xg < 3.4
    assert projection.away_xg > 0.3


def test_devig_removes_overround() -> None:
    fair = devig({"HOME": 1.90, "DRAW": 3.40, "AWAY": 4.30})
    assert math.isclose(sum(fair.values()), 1.0, abs_tol=1e-12)


def test_market_shrinkage_dominates_model() -> None:
    blended = blend_probabilities(
        {"HOME": 0.50, "DRAW": 0.30, "AWAY": 0.20},
        {"HOME": 0.80, "DRAW": 0.15, "AWAY": 0.05},
        {"HOME": 0.70, "DRAW": 0.20, "AWAY": 0.10},
    )
    assert 0.50 < blended["HOME"] < 0.60


def test_ev_and_settlement() -> None:
    assert math.isclose(expected_value(0.55, 2.0), 0.10)
    assert settle("1X2", "HOME", 2, 1) == "WIN"
    assert settle("TOTAL_2_5", "UNDER_2_5", 1, 1) == "WIN"
    assert settle("BTTS", "BTTS_YES", 1, 0) == "LOSS"

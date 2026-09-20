from __future__ import annotations

import pytest

from model.settlement import (
    pnl_for_settlement,
    settle_handicap,
    settle_total,
    split_asian_line,
)


def test_split_quarter_lines() -> None:
    assert split_asian_line(2.25) == (2.0, 2.5)
    assert split_asian_line(2.75) == (2.5, 3.0)
    assert split_asian_line(-1.25) == (-1.5, -1.0)
    assert split_asian_line(3.5) == (3.5,)


def test_total_quarter_half_loss() -> None:
    result = settle_total(actual=2, selection="over", line=2.25)
    assert result.result == "HL"
    assert result.win_stake == 0.0
    assert result.push_stake == 0.5
    assert result.loss_stake == 0.5


def test_total_under_wins() -> None:
    result = settle_total(actual=2, selection="under", line=2.75)
    assert result.result == "W"
    assert result.win_stake == 1.0
    assert result.loss_stake == 0.0


def test_handicap_plus_five_and_half_wins() -> None:
    result = settle_handicap(selected_actual=1, opponent_actual=4, handicap=5.5)
    assert result.result == "W"
    assert result.win_stake == 1.0


def test_handicap_quarter_half_win() -> None:
    result = settle_handicap(selected_actual=2, opponent_actual=1, handicap=-0.75)
    assert result.result == "HW"
    assert result.win_stake == 0.5
    assert result.push_stake == 0.5
    assert result.loss_stake == 0.0


def test_reference_pnl_respects_half_loss() -> None:
    result = settle_total(actual=2, selection="over", line=2.25)
    assert pnl_for_settlement(result, 2.0) == pytest.approx(-0.5)


def test_reject_non_quarter_line() -> None:
    with pytest.raises(ValueError):
        split_asian_line(2.3)

from model.stat_markets import asian_handicap, asian_team_total, h2h


def test_h2h_symmetric_means_are_symmetric() -> None:
    market = h2h(5.0, 5.0)
    assert abs(market.first_win - market.second_win) < 1e-12
    assert market.tie > 0


def test_integer_team_total_has_push_probability() -> None:
    market = asian_team_total(mean=5.0, line=5.0, side="over")
    assert market.push > 0
    assert market.fair_odds is not None


def test_quarter_handicap_has_valid_fair_price() -> None:
    market = asian_handicap(
        first_mean=6.0,
        second_mean=5.0,
        line=-0.25,
    )
    assert market.fair_odds is not None
    assert market.fair_odds > 1.0

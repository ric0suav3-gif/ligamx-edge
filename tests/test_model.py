from model.distributions import one_x_two_from_goals
from model.ewma import ewma
from model.league_strength import cross_league_expectation


def test_ewma_prefers_recent_observations() -> None:
    assert ewma([1.0, 1.0, 5.0], half_life=1.0) > 2.5


def test_one_x_two_sums_to_one() -> None:
    p = one_x_two_from_goals(1.6, 1.1)
    assert abs((p.home + p.draw + p.away) - 1.0) < 1e-9


def test_cross_league_baseline_is_identity_when_indices_are_one() -> None:
    projected = cross_league_expectation(
        ucl_baseline=1.5,
        attack_rate=1.5,
        attack_league_baseline=1.5,
        opponent_conceded_rate=1.5,
        opponent_league_baseline=1.5,
        strength_multiplier=1.0,
        shrinkage=0.65,
    )
    assert abs(projected - 1.5) < 1e-9

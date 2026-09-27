from __future__ import annotations

from dataclasses import dataclass

from .distributions import OneXTwo, one_x_two_from_goals
from .league_strength import (
    association_strength_multiplier,
    cross_league_expectation,
    elo_goal_multiplier,
    shrink_rate,
)


@dataclass(frozen=True)
class DomesticGoalProfile:
    team_id: int
    home_for: float
    home_against: float
    away_for: float
    away_against: float
    league_home_goals: float
    league_away_goals: float
    home_n: int
    away_n: int
    association_coeff: float
    elo: float = 1500.0


@dataclass(frozen=True)
class UCLProjection:
    home_xg: float
    away_xg: float
    one_x_two: OneXTwo


def project_goals(
    home: DomesticGoalProfile,
    away: DomesticGoalProfile,
    ucl_home_baseline: float,
    ucl_away_baseline: float,
    shrinkage: float = 0.60,
    split_prior_matches: float = 12.0,
) -> UCLProjection:
    # First shrink noisy home/away split rates toward each domestic league's
    # scoring environment. With ~15 matches in a split, raw 3.0+ goal rates
    # should not transfer to Europe at full weight.
    home_for = shrink_rate(
        home.home_for, home.league_home_goals, home.home_n, split_prior_matches
    )
    home_against = shrink_rate(
        home.home_against, home.league_away_goals, home.home_n, split_prior_matches
    )
    away_for = shrink_rate(
        away.away_for, away.league_away_goals, away.away_n, split_prior_matches
    )
    away_against = shrink_rate(
        away.away_against, away.league_home_goals, away.away_n, split_prior_matches
    )

    # Domestic-rate indices describe relative quality inside each league.
    # Association coefficients provide the missing cross-league anchor.
    home_assoc = association_strength_multiplier(
        home.association_coeff, away.association_coeff
    )
    away_assoc = association_strength_multiplier(
        away.association_coeff, home.association_coeff
    )

    # Club Elo is kept as a secondary, deliberately mild correction.
    home_elo = elo_goal_multiplier(home.elo, away.elo)
    away_elo = elo_goal_multiplier(away.elo, home.elo)

    home_xg = cross_league_expectation(
        ucl_baseline=ucl_home_baseline,
        attack_rate=home_for,
        attack_league_baseline=home.league_home_goals,
        opponent_conceded_rate=away_against,
        opponent_league_baseline=away.league_home_goals,
        strength_multiplier=home_assoc * home_elo,
        shrinkage=shrinkage,
    )
    away_xg = cross_league_expectation(
        ucl_baseline=ucl_away_baseline,
        attack_rate=away_for,
        attack_league_baseline=away.league_away_goals,
        opponent_conceded_rate=home_against,
        opponent_league_baseline=home.league_away_goals,
        strength_multiplier=away_assoc * away_elo,
        shrinkage=shrinkage,
    )

    return UCLProjection(
        home_xg=home_xg,
        away_xg=away_xg,
        one_x_two=one_x_two_from_goals(home_xg, away_xg),
    )

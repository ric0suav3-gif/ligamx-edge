from __future__ import annotations

from dataclasses import dataclass

from .distributions import OneXTwo, one_x_two_from_goals
from .league_strength import cross_league_expectation, elo_goal_multiplier


@dataclass(frozen=True)
class DomesticGoalProfile:
    team_id: int
    home_for: float
    home_against: float
    away_for: float
    away_against: float
    league_home_goals: float
    league_away_goals: float
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
    shrinkage: float = 0.65,
) -> UCLProjection:
    home_strength = elo_goal_multiplier(home.elo, away.elo)
    away_strength = elo_goal_multiplier(away.elo, home.elo)

    home_xg = cross_league_expectation(
        ucl_baseline=ucl_home_baseline,
        attack_rate=home.home_for,
        attack_league_baseline=home.league_home_goals,
        opponent_conceded_rate=away.away_against,
        opponent_league_baseline=away.league_home_goals,
        strength_multiplier=home_strength,
        shrinkage=shrinkage,
    )
    away_xg = cross_league_expectation(
        ucl_baseline=ucl_away_baseline,
        attack_rate=away.away_for,
        attack_league_baseline=away.league_away_goals,
        opponent_conceded_rate=home.home_against,
        opponent_league_baseline=home.league_away_goals,
        strength_multiplier=away_strength,
        shrinkage=shrinkage,
    )

    return UCLProjection(
        home_xg=home_xg,
        away_xg=away_xg,
        one_x_two=one_x_two_from_goals(home_xg, away_xg),
    )

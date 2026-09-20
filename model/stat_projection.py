from __future__ import annotations

from dataclasses import dataclass

from .league_strength import shrink_rate


@dataclass(frozen=True)
class SplitStatProfile:
    for_rate: float
    against_rate: float
    n: int


@dataclass(frozen=True)
class TeamStatProfile:
    team_id: int
    home: SplitStatProfile
    away: SplitStatProfile
    league_home_mean: float
    league_away_mean: float


@dataclass(frozen=True)
class StatProjection:
    home_mean: float
    away_mean: float


def _relative(rate: float, baseline: float) -> float:
    if baseline <= 0:
        raise ValueError("baseline must be positive")
    return rate / baseline


def project_stat(
    home: TeamStatProfile,
    away: TeamStatProfile,
    ucl_home_mean: float,
    ucl_away_mean: float,
    split_prior_matches: float = 12.0,
    matchup_shrinkage: float = 0.55,
    home_transfer: float = 1.0,
    away_transfer: float = 1.0,
) -> StatProjection:
    """Transfer domestic stat profiles onto the UCL environment.

    v0.1 deliberately keeps cross-league transfer factors at 1.0 unless they
    are supplied from a separately estimated, stat-specific European model.
    This avoids pretending one generic league-strength multiplier applies to
    shots, SOT, corners, fouls, cards, and offsides equally.
    """
    h_for = shrink_rate(
        home.home.for_rate,
        home.league_home_mean,
        home.home.n,
        split_prior_matches,
    )
    h_against = shrink_rate(
        home.home.against_rate,
        home.league_away_mean,
        home.home.n,
        split_prior_matches,
    )
    a_for = shrink_rate(
        away.away.for_rate,
        away.league_away_mean,
        away.away.n,
        split_prior_matches,
    )
    a_against = shrink_rate(
        away.away.against_rate,
        away.league_home_mean,
        away.away.n,
        split_prior_matches,
    )

    raw_home = (
        ucl_home_mean
        * _relative(h_for, home.league_home_mean)
        * _relative(a_against, away.league_home_mean)
        * home_transfer
    )
    raw_away = (
        ucl_away_mean
        * _relative(a_for, away.league_away_mean)
        * _relative(h_against, home.league_away_mean)
        * away_transfer
    )

    home_mean = matchup_shrinkage * raw_home + (1.0 - matchup_shrinkage) * ucl_home_mean
    away_mean = matchup_shrinkage * raw_away + (1.0 - matchup_shrinkage) * ucl_away_mean
    return StatProjection(home_mean=home_mean, away_mean=away_mean)

from __future__ import annotations


def relative_index(team_rate: float, league_rate: float) -> float:
    if league_rate <= 0:
        raise ValueError("league_rate must be positive")
    return team_rate / league_rate


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def elo_goal_multiplier(
    team_elo: float,
    opponent_elo: float,
    divisor: float = 1600.0,
    low: float = 0.75,
    high: float = 1.33,
) -> float:
    """Conservative Elo-to-count multiplier.

    This is intentionally mild and must be re-fit by walk-forward backtesting.
    """
    raw = 10 ** ((team_elo - opponent_elo) / divisor)
    return clamp(raw, low, high)


def cross_league_expectation(
    ucl_baseline: float,
    attack_rate: float,
    attack_league_baseline: float,
    opponent_conceded_rate: float,
    opponent_league_baseline: float,
    strength_multiplier: float = 1.0,
    shrinkage: float = 0.65,
) -> float:
    """Project one team's count rate across different domestic environments.

    Both team inputs are first expressed relative to their own domestic
    baselines, then transferred onto a UCL baseline.
    """
    attack = relative_index(attack_rate, attack_league_baseline)
    concession = relative_index(
        opponent_conceded_rate, opponent_league_baseline
    )
    raw = ucl_baseline * attack * concession * strength_multiplier
    return shrinkage * raw + (1.0 - shrinkage) * ucl_baseline

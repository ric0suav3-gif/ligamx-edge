from __future__ import annotations


def relative_index(team_rate: float, league_rate: float) -> float:
    if league_rate <= 0:
        raise ValueError("league_rate must be positive")
    return team_rate / league_rate


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def shrink_rate(
    rate: float,
    baseline: float,
    n: int,
    prior_matches: float = 12.0,
) -> float:
    """Empirical-Bayes-style shrinkage of a split rate toward league average."""
    if n < 0:
        raise ValueError("n must be non-negative")
    weight = n / (n + prior_matches) if (n + prior_matches) > 0 else 0.0
    return weight * rate + (1.0 - weight) * baseline


def elo_goal_multiplier(
    team_elo: float,
    opponent_elo: float,
    divisor: float = 1800.0,
    low: float = 0.80,
    high: float = 1.25,
) -> float:
    """Mild club-level strength correction.

    The European Elo is intentionally not allowed to dominate the domestic-rate
    features because the v0 Elo pool includes clubs from different UEFA tiers.
    """
    raw = 10 ** ((team_elo - opponent_elo) / divisor)
    return clamp(raw, low, high)


def association_strength_multiplier(
    team_coeff: float,
    opponent_coeff: float,
    exponent: float = 0.35,
    low: float = 0.78,
    high: float = 1.28,
) -> float:
    """Translate domestic performance between league-strength environments.

    UEFA association coefficients are used only as a conservative prior, not as
    a direct probability model. The exponent strongly dampens the raw ratio.
    """
    if team_coeff <= 0 or opponent_coeff <= 0:
        return 1.0
    raw = (team_coeff / opponent_coeff) ** exponent
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

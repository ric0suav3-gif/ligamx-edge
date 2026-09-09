from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from nfl.model.ewma import ewma


@dataclass(frozen=True)
class TeamStatProjection:
    team_id: int
    team_name: str
    expected_plays: float
    expected_pass_attempts: float
    expected_completions: float
    expected_rush_attempts: float
    expected_passing_yards: float
    expected_rushing_yards: float
    expected_sacks_made: float
    expected_turnovers: float
    expected_points: float
    pass_rate: float
    completion_rate: float
    yards_per_pass_attempt: float
    yards_per_rush_attempt: float
    reliability: str
    history_games: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series(
    matches: list[dict[str, Any]],
    container: str,
    field: str,
) -> list[float | None]:
    return [
        _num((row.get(container) or {}).get(field))
        for row in matches
    ]


def _weighted_pair(
    own_value: float | None,
    opponent_allowed: float | None,
    own_weight: float = 0.60,
) -> float | None:
    if own_value is None and opponent_allowed is None:
        return None
    if own_value is None:
        return opponent_allowed
    if opponent_allowed is None:
        return own_value
    return own_weight * own_value + (1.0 - own_weight) * opponent_allowed


def _ratio_series(
    matches: list[dict[str, Any]],
    container: str,
    numerator: str,
    denominator: str,
) -> list[float | None]:
    out: list[float | None] = []
    for row in matches:
        stats = row.get(container) or {}
        num = _num(stats.get(numerator))
        den = _num(stats.get(denominator))
        if num is None or den in (None, 0):
            out.append(None)
        else:
            out.append(num / den)
    return out


def project_team_stats(
    *,
    team_id: int,
    team_name: str,
    own_matches: list[dict[str, Any]],
    opponent_matches: list[dict[str, Any]],
    half_life: float = 8.0,
) -> TeamStatProjection | None:
    if not own_matches:
        return None

    # Expected scrimmage attempts. This is more coherent than separately
    # forecasting pass attempts and rush attempts and then letting their sum
    # drift away from the team's historical offensive volume.
    own_scrimmage = [
        (
            _num((row.get("team") or {}).get("pass_attempts"))
            + _num((row.get("team") or {}).get("rush_attempts"))
        )
        if _num((row.get("team") or {}).get("pass_attempts")) is not None
        and _num((row.get("team") or {}).get("rush_attempts")) is not None
        else None
        for row in own_matches
    ]
    allowed_scrimmage = [
        (
            _num((row.get("opponent_team") or {}).get("pass_attempts"))
            + _num((row.get("opponent_team") or {}).get("rush_attempts"))
        )
        if _num((row.get("opponent_team") or {}).get("pass_attempts")) is not None
        and _num((row.get("opponent_team") or {}).get("rush_attempts")) is not None
        else None
        for row in opponent_matches
    ]
    expected_scrimmage = _weighted_pair(
        ewma(own_scrimmage, half_life),
        ewma(allowed_scrimmage, half_life),
    )
    if expected_scrimmage is None or expected_scrimmage <= 0:
        return None

    own_pass_rate = ewma(
        [
            (
                _num((row.get("team") or {}).get("pass_attempts"))
                / (
                    _num((row.get("team") or {}).get("pass_attempts"))
                    + _num((row.get("team") or {}).get("rush_attempts"))
                )
            )
            if _num((row.get("team") or {}).get("pass_attempts")) is not None
            and _num((row.get("team") or {}).get("rush_attempts")) is not None
            and (
                _num((row.get("team") or {}).get("pass_attempts"))
                + _num((row.get("team") or {}).get("rush_attempts"))
            ) > 0
            else None
            for row in own_matches
        ],
        half_life,
    )
    allowed_pass_rate = ewma(
        [
            (
                _num((row.get("opponent_team") or {}).get("pass_attempts"))
                / (
                    _num((row.get("opponent_team") or {}).get("pass_attempts"))
                    + _num((row.get("opponent_team") or {}).get("rush_attempts"))
                )
            )
            if _num((row.get("opponent_team") or {}).get("pass_attempts")) is not None
            and _num((row.get("opponent_team") or {}).get("rush_attempts")) is not None
            and (
                _num((row.get("opponent_team") or {}).get("pass_attempts"))
                + _num((row.get("opponent_team") or {}).get("rush_attempts"))
            ) > 0
            else None
            for row in opponent_matches
        ],
        half_life,
    )
    pass_rate = _weighted_pair(own_pass_rate, allowed_pass_rate)
    if pass_rate is None:
        return None
    pass_rate = max(0.35, min(0.75, pass_rate))

    expected_pass_attempts = expected_scrimmage * pass_rate
    expected_rush_attempts = expected_scrimmage - expected_pass_attempts

    own_completion_rate = ewma(
        _ratio_series(own_matches, "team", "pass_completions", "pass_attempts"),
        half_life,
    )
    allowed_completion_rate = ewma(
        _ratio_series(
            opponent_matches,
            "opponent_team",
            "pass_completions",
            "pass_attempts",
        ),
        half_life,
    )
    completion_rate = _weighted_pair(
        own_completion_rate,
        allowed_completion_rate,
    )
    completion_rate = 0.64 if completion_rate is None else completion_rate
    completion_rate = max(0.45, min(0.80, completion_rate))
    expected_completions = expected_pass_attempts * completion_rate

    own_ypa = ewma(
        _ratio_series(
            own_matches,
            "team",
            "team_net_passing_yards",
            "pass_attempts",
        ),
        half_life,
    )
    allowed_ypa = ewma(
        _ratio_series(
            opponent_matches,
            "opponent_team",
            "team_net_passing_yards",
            "pass_attempts",
        ),
        half_life,
    )
    ypa = _weighted_pair(own_ypa, allowed_ypa)
    ypa = 6.5 if ypa is None else max(3.0, min(10.0, ypa))
    expected_passing_yards = expected_pass_attempts * ypa

    own_ypc = ewma(
        _ratio_series(own_matches, "team", "rushing_yards", "rush_attempts"),
        half_life,
    )
    allowed_ypc = ewma(
        _ratio_series(
            opponent_matches,
            "opponent_team",
            "rushing_yards",
            "rush_attempts",
        ),
        half_life,
    )
    ypc = _weighted_pair(own_ypc, allowed_ypc)
    ypc = 4.3 if ypc is None else max(2.5, min(7.0, ypc))
    expected_rushing_yards = expected_rush_attempts * ypc

    own_sacks = ewma(_series(own_matches, "team", "sacks_made"), half_life)
    opponent_sacks_taken = ewma(
        _series(opponent_matches, "team", "sacks_taken"),
        half_life,
    )
    sacks = _weighted_pair(own_sacks, opponent_sacks_taken, own_weight=0.50)
    sacks = 2.5 if sacks is None else max(0.0, sacks)

    own_turnovers = ewma(_series(own_matches, "team", "turnovers"), half_life)
    opponent_takeaways = ewma(
        _series(opponent_matches, "opponent_team", "turnovers"),
        half_life,
    )
    turnovers = _weighted_pair(own_turnovers, opponent_takeaways, own_weight=0.60)
    turnovers = 1.2 if turnovers is None else max(0.0, turnovers)

    # A team's points scored in one historical row equal the opponent's
    # "points_against"; opponent defensive points allowed are in team.points_against.
    own_points_for = ewma(
        _series(own_matches, "opponent_team", "points_against"),
        half_life,
    )
    opponent_points_allowed = ewma(
        _series(opponent_matches, "team", "points_against"),
        half_life,
    )
    points = _weighted_pair(own_points_for, opponent_points_allowed)
    points = 22.0 if points is None else max(0.0, points)

    # API "plays" can include sacks whereas pass_attempts + rush_attempts does not,
    # so project it separately for display/diagnostics.
    expected_plays = _weighted_pair(
        ewma(_series(own_matches, "team", "plays"), half_life),
        ewma(_series(opponent_matches, "opponent_team", "plays"), half_life),
    )
    if expected_plays is None:
        expected_plays = expected_scrimmage + sacks

    n = len(own_matches)
    reliability = "HIGH" if n >= 16 else "MEDIUM" if n >= 8 else "LOW"

    return TeamStatProjection(
        team_id=team_id,
        team_name=team_name,
        expected_plays=expected_plays,
        expected_pass_attempts=expected_pass_attempts,
        expected_completions=expected_completions,
        expected_rush_attempts=expected_rush_attempts,
        expected_passing_yards=expected_passing_yards,
        expected_rushing_yards=expected_rushing_yards,
        expected_sacks_made=sacks,
        expected_turnovers=turnovers,
        expected_points=points,
        pass_rate=pass_rate,
        completion_rate=completion_rate,
        yards_per_pass_attempt=ypa,
        yards_per_rush_attempt=ypc,
        reliability=reliability,
        history_games=n,
    )

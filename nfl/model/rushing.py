from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import stdev
from typing import Any

from nfl.model.distributions import fit_count_distribution
from nfl.model.ewma import ewma


@dataclass(frozen=True)
class RushingProjection:
    player_name: str
    team_id: int
    team_name: str
    games_active: int
    team_games: int
    expected_team_rush_attempts: float
    expected_attempts: float
    carry_share: float
    yards_per_attempt: float
    expected_rushing_yards: float
    attempts_r: float | None
    rushing_yards_sd: float
    reliability: str
    reason: str


def _player_for_game(row: dict[str, Any], player_name: str) -> dict[str, Any] | None:
    target = player_name.casefold().strip()
    for player in row.get("players") or []:
        if str(player.get("player_name") or "").casefold().strip() == target:
            return player
    return None


def _valid_num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def project_team_rush_attempts(
    own_matches: list[dict[str, Any]],
    opp_matches: list[dict[str, Any]],
    half_life: float = 8.0,
    own_weight: float = 0.60,
) -> float | None:
    own = [
        _valid_num((row.get("team") or {}).get("rush_attempts"))
        for row in own_matches
    ]
    # In the opponent history, opponent_team is what that defense allowed.
    allowed = [
        _valid_num((row.get("opponent_team") or {}).get("rush_attempts"))
        for row in opp_matches
    ]
    own_rate = ewma(own, half_life=half_life)
    allowed_rate = ewma(allowed, half_life=half_life)

    if own_rate is None and allowed_rate is None:
        return None
    if own_rate is None:
        return allowed_rate
    if allowed_rate is None:
        return own_rate
    return own_weight * own_rate + (1.0 - own_weight) * allowed_rate


def project_player_rushing(
    *,
    player_name: str,
    team_id: int,
    team_name: str,
    own_matches: list[dict[str, Any]],
    opp_matches: list[dict[str, Any]],
    half_life: float = 8.0,
) -> RushingProjection | None:
    team_rush = project_team_rush_attempts(
        own_matches,
        opp_matches,
        half_life=half_life,
    )
    if team_rush is None or team_rush <= 0:
        return None

    shares: list[float | None] = []
    attempts_series: list[float | None] = []
    ypc_series: list[float | None] = []
    yards_series: list[float] = []

    for row in own_matches:
        player = _player_for_game(row, player_name)
        if player is None:
            shares.append(None)
            attempts_series.append(None)
            ypc_series.append(None)
            continue

        rush = player.get("rushing") or {}
        attempts = _valid_num(rush.get("attempts"))
        yards = _valid_num(rush.get("yards"))
        team_attempts = _valid_num((row.get("team") or {}).get("rush_attempts"))

        attempts_series.append(attempts)
        if attempts is not None and team_attempts and team_attempts > 0:
            shares.append(max(0.0, min(1.0, attempts / team_attempts)))
        else:
            shares.append(None)

        if attempts is not None and attempts > 0 and yards is not None:
            ypc_series.append(yards / attempts)
            yards_series.append(yards)
        else:
            ypc_series.append(None)
            if yards is not None:
                yards_series.append(yards)

    carry_share = ewma(shares, half_life=half_life)
    player_ypc = ewma(ypc_series, half_life=half_life)
    attempts_clean = [x for x in attempts_series if x is not None]

    if carry_share is None or player_ypc is None or not attempts_clean:
        return None

    # Shrink extreme small-sample shares very lightly toward a neutral 20%
    # backfield share. This is deliberately conservative for v0.1.
    n_active = len(attempts_clean)
    prior_games = 3.0
    shrunk_share = (
        n_active * carry_share + prior_games * 0.20
    ) / (n_active + prior_games)

    expected_attempts = max(0.0, team_rush * shrunk_share)

    own_team_ypc = ewma(
        [
            (
                _valid_num((row.get("team") or {}).get("rushing_yards"))
                / _valid_num((row.get("team") or {}).get("rush_attempts"))
            )
            if _valid_num((row.get("team") or {}).get("rush_attempts"))
            not in (None, 0)
            and _valid_num((row.get("team") or {}).get("rushing_yards")) is not None
            else None
            for row in own_matches
        ],
        half_life=half_life,
    )
    opp_allowed_ypc = ewma(
        [
            (
                _valid_num((row.get("opponent_team") or {}).get("rushing_yards"))
                / _valid_num((row.get("opponent_team") or {}).get("rush_attempts"))
            )
            if _valid_num((row.get("opponent_team") or {}).get("rush_attempts"))
            not in (None, 0)
            and _valid_num((row.get("opponent_team") or {}).get("rushing_yards")) is not None
            else None
            for row in opp_matches
        ],
        half_life=half_life,
    )

    components = [(player_ypc, 0.60)]
    if own_team_ypc is not None:
        components.append((own_team_ypc, 0.20))
    if opp_allowed_ypc is not None:
        components.append((opp_allowed_ypc, 0.20))
    total_w = sum(w for _, w in components)
    ypc = sum(value * w for value, w in components) / total_w
    ypc = max(1.0, min(8.0, ypc))

    expected_yards = expected_attempts * ypc

    try:
        fit = fit_count_distribution(attempts_clean)
        attempts_r = fit.r
    except ValueError:
        attempts_r = None

    sample_sd = stdev(yards_series) if len(yards_series) >= 2 else 0.0
    yards_sd = max(8.0, sample_sd, 0.45 * max(expected_yards, 1.0))

    if n_active >= 12:
        reliability = "HIGH"
    elif n_active >= 6:
        reliability = "MEDIUM"
    else:
        reliability = "LOW"

    reason = (
        f"active rushing sample n={n_active}; "
        f"team-history n={len(own_matches)}; team-tenure history only"
    )

    return RushingProjection(
        player_name=player_name,
        team_id=team_id,
        team_name=team_name,
        games_active=n_active,
        team_games=len(own_matches),
        expected_team_rush_attempts=team_rush,
        expected_attempts=expected_attempts,
        carry_share=shrunk_share,
        yards_per_attempt=ypc,
        expected_rushing_yards=expected_yards,
        attempts_r=attempts_r,
        rushing_yards_sd=yards_sd,
        reliability=reliability,
        reason=reason,
    )

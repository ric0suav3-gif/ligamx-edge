from __future__ import annotations

from dataclasses import dataclass
from statistics import stdev
from typing import Any

from nfl.model.distributions import fit_count_distribution
from nfl.model.ewma import ewma


@dataclass(frozen=True)
class PassingProjection:
    player_name: str
    team_id: int
    team_name: str
    games_active: int
    team_games: int
    expected_team_pass_attempts: float
    expected_attempts: float
    completion_rate: float
    expected_completions: float
    yards_per_attempt: float
    expected_passing_yards: float
    expected_passing_touchdowns: float
    expected_interceptions: float
    attempts_r: float | None
    completions_sd: float
    passing_yards_sd: float
    reliability: str
    reason: str


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _player_for_game(row: dict[str, Any], player_name: str) -> dict[str, Any] | None:
    target = player_name.casefold().strip()
    for player in row.get("players") or []:
        if str(player.get("player_name") or "").casefold().strip() == target:
            return player
    return None


def project_team_pass_attempts(
    own_matches: list[dict[str, Any]],
    opp_matches: list[dict[str, Any]],
    half_life: float = 8.0,
    own_weight: float = 0.60,
) -> float | None:
    own = [_num((row.get("team") or {}).get("pass_attempts")) for row in own_matches]
    allowed = [
        _num((row.get("opponent_team") or {}).get("pass_attempts"))
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


def project_player_passing(
    *,
    player_name: str,
    team_id: int,
    team_name: str,
    own_matches: list[dict[str, Any]],
    opp_matches: list[dict[str, Any]],
    half_life: float = 8.0,
) -> PassingProjection | None:
    team_pass = project_team_pass_attempts(
        own_matches,
        opp_matches,
        half_life=half_life,
    )
    if team_pass is None or team_pass <= 0:
        return None

    shares: list[float | None] = []
    attempts_series: list[float | None] = []
    completion_rates: list[float | None] = []
    ypa_series: list[float | None] = []
    td_rates: list[float | None] = []
    int_rates: list[float | None] = []
    completions_values: list[float] = []
    yards_values: list[float] = []

    for row in own_matches:
        player = _player_for_game(row, player_name)
        passing = (player or {}).get("passing") or {}
        attempts = _num(passing.get("attempts"))
        completions = _num(passing.get("completions"))
        yards = _num(passing.get("yards"))
        tds = _num(passing.get("touchdowns"))
        ints = _num(passing.get("interceptions"))
        team_attempts = _num((row.get("team") or {}).get("pass_attempts"))

        attempts_series.append(attempts)
        if attempts is not None and team_attempts and team_attempts > 0:
            shares.append(max(0.0, min(1.0, attempts / team_attempts)))
        else:
            shares.append(None)

        if attempts is not None and attempts > 0:
            completion_rates.append(
                None if completions is None else max(0.0, min(1.0, completions / attempts))
            )
            ypa_series.append(None if yards is None else yards / attempts)
            td_rates.append(None if tds is None else tds / attempts)
            int_rates.append(None if ints is None else ints / attempts)
        else:
            completion_rates.append(None)
            ypa_series.append(None)
            td_rates.append(None)
            int_rates.append(None)

        if completions is not None:
            completions_values.append(completions)
        if yards is not None:
            yards_values.append(yards)

    attempts_clean = [x for x in attempts_series if x is not None and x > 0]
    if not attempts_clean:
        return None

    share = ewma(shares, half_life=half_life)
    comp_rate = ewma(completion_rates, half_life=half_life)
    player_ypa = ewma(ypa_series, half_life=half_life)
    td_rate = ewma(td_rates, half_life=half_life)
    int_rate = ewma(int_rates, half_life=half_life)

    if share is None or comp_rate is None or player_ypa is None:
        return None

    n_active = len(attempts_clean)
    prior_games = 2.0
    # Starting QBs usually own nearly all team attempts. Shrinking toward 90%
    # protects against spot starts and partial games without forcing 100%.
    share = (n_active * share + prior_games * 0.90) / (n_active + prior_games)
    share = max(0.10, min(1.0, share))
    expected_attempts = team_pass * share

    # Mild Bayesian shrinkage for rates.
    comp_rate = (n_active * comp_rate + 4.0 * 0.64) / (n_active + 4.0)
    comp_rate = max(0.35, min(0.82, comp_rate))
    expected_completions = expected_attempts * comp_rate

    own_net_ypa = ewma(
        [
            (
                _num((row.get("team") or {}).get("team_net_passing_yards"))
                / _num((row.get("team") or {}).get("pass_attempts"))
            )
            if _num((row.get("team") or {}).get("pass_attempts")) not in (None, 0)
            and _num((row.get("team") or {}).get("team_net_passing_yards")) is not None
            else None
            for row in own_matches
        ],
        half_life=half_life,
    )
    opp_allowed_net_ypa = ewma(
        [
            (
                _num((row.get("opponent_team") or {}).get("team_net_passing_yards"))
                / _num((row.get("opponent_team") or {}).get("pass_attempts"))
            )
            if _num((row.get("opponent_team") or {}).get("pass_attempts")) not in (None, 0)
            and _num((row.get("opponent_team") or {}).get("team_net_passing_yards")) is not None
            else None
            for row in opp_matches
        ],
        half_life=half_life,
    )

    components = [(player_ypa, 0.70)]
    if own_net_ypa is not None:
        components.append((own_net_ypa, 0.15))
    if opp_allowed_net_ypa is not None:
        components.append((opp_allowed_net_ypa, 0.15))
    weight = sum(w for _, w in components)
    ypa = sum(value * w for value, w in components) / weight
    ypa = max(3.0, min(10.5, ypa))
    expected_yards = expected_attempts * ypa

    td_rate = 0.045 if td_rate is None else (n_active * td_rate + 8.0 * 0.045) / (n_active + 8.0)
    int_rate = 0.023 if int_rate is None else (n_active * int_rate + 8.0 * 0.023) / (n_active + 8.0)

    try:
        attempts_fit = fit_count_distribution(attempts_clean)
        attempts_r = attempts_fit.r
    except ValueError:
        attempts_r = None

    completions_sd = max(
        2.5,
        stdev(completions_values) if len(completions_values) >= 2 else 0.0,
        (expected_attempts * comp_rate * (1.0 - comp_rate)) ** 0.5,
    )
    passing_yards_sd = max(
        35.0,
        stdev(yards_values) if len(yards_values) >= 2 else 0.0,
        0.22 * max(expected_yards, 1.0),
    )

    reliability = "HIGH" if n_active >= 12 else "MEDIUM" if n_active >= 6 else "LOW"
    reason = (
        f"active passing sample n={n_active}; team-history n={len(own_matches)}; "
        "team-tenure history only"
    )

    return PassingProjection(
        player_name=player_name,
        team_id=team_id,
        team_name=team_name,
        games_active=n_active,
        team_games=len(own_matches),
        expected_team_pass_attempts=team_pass,
        expected_attempts=expected_attempts,
        completion_rate=comp_rate,
        expected_completions=expected_completions,
        yards_per_attempt=ypa,
        expected_passing_yards=expected_yards,
        expected_passing_touchdowns=expected_attempts * td_rate,
        expected_interceptions=expected_attempts * int_rate,
        attempts_r=attempts_r,
        completions_sd=completions_sd,
        passing_yards_sd=passing_yards_sd,
        reliability=reliability,
        reason=reason,
    )

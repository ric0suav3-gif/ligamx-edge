from __future__ import annotations

from dataclasses import dataclass
from statistics import stdev
from typing import Any

from nfl.model.ewma import ewma
from nfl.model.passing import project_team_pass_attempts


@dataclass(frozen=True)
class ReceivingProjection:
    player_name: str
    team_id: int
    team_name: str
    games_active: int
    team_games: int
    expected_team_pass_attempts: float
    target_share: float
    expected_targets: float
    catch_rate: float
    expected_receptions: float
    yards_per_target: float
    expected_receiving_yards: float
    receiving_yards_sd: float
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


def project_player_receiving(
    *,
    player_name: str,
    team_id: int,
    team_name: str,
    own_matches: list[dict[str, Any]],
    opp_matches: list[dict[str, Any]],
    half_life: float = 8.0,
) -> ReceivingProjection | None:
    team_pass = project_team_pass_attempts(
        own_matches,
        opp_matches,
        half_life=half_life,
    )
    if team_pass is None or team_pass <= 0:
        return None

    target_shares: list[float | None] = []
    catch_rates: list[float | None] = []
    ypt_values: list[float | None] = []
    receiving_yards: list[float] = []
    active = 0

    for row in own_matches:
        player = _player_for_game(row, player_name)
        receiving = (player or {}).get("receiving") or {}
        targets = _num(receiving.get("targets"))
        receptions = _num(receiving.get("receptions"))
        yards = _num(receiving.get("yards"))
        team_attempts = _num((row.get("team") or {}).get("pass_attempts"))

        if targets is None:
            target_shares.append(None)
            catch_rates.append(None)
            ypt_values.append(None)
            continue

        active += 1
        if team_attempts and team_attempts > 0:
            target_shares.append(max(0.0, min(1.0, targets / team_attempts)))
        else:
            target_shares.append(None)

        if targets > 0:
            catch_rates.append(
                None if receptions is None else max(0.0, min(1.0, receptions / targets))
            )
            ypt_values.append(None if yards is None else yards / targets)
        else:
            catch_rates.append(None)
            ypt_values.append(None)

        if yards is not None:
            receiving_yards.append(yards)

    if active == 0:
        return None

    share = ewma(target_shares, half_life=half_life)
    catch_rate = ewma(catch_rates, half_life=half_life)
    ypt = ewma(ypt_values, half_life=half_life)

    if share is None or catch_rate is None or ypt is None:
        return None

    # A small prior stabilizes volatile small-sample target shares.
    share = (active * share + 3.0 * 0.12) / (active + 3.0)
    share = max(0.01, min(0.40, share))
    expected_targets = team_pass * share

    catch_rate = (active * catch_rate + 5.0 * 0.65) / (active + 5.0)
    catch_rate = max(0.35, min(0.90, catch_rate))
    expected_receptions = expected_targets * catch_rate

    # Receiving efficiency is noisy. Shrink toward a neutral 7.5 yards/target.
    ypt = (active * ypt + 6.0 * 7.5) / (active + 6.0)
    ypt = max(3.0, min(13.0, ypt))
    expected_yards = expected_targets * ypt

    yards_sd = max(
        18.0,
        stdev(receiving_yards) if len(receiving_yards) >= 2 else 0.0,
        0.55 * max(expected_yards, 1.0),
    )

    reliability = "HIGH" if active >= 12 else "MEDIUM" if active >= 6 else "LOW"
    reason = (
        f"receiving sample n={active}; team-history n={len(own_matches)}; "
        "team-tenure history only"
    )

    return ReceivingProjection(
        player_name=player_name,
        team_id=team_id,
        team_name=team_name,
        games_active=active,
        team_games=len(own_matches),
        expected_team_pass_attempts=team_pass,
        target_share=share,
        expected_targets=expected_targets,
        catch_rate=catch_rate,
        expected_receptions=expected_receptions,
        yards_per_target=ypt,
        expected_receiving_yards=expected_yards,
        receiving_yards_sd=yards_sd,
        reliability=reliability,
        reason=reason,
    )

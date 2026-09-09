from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text or text in {"-", "—", "null", "None"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _pair(value: Any, sep: str = "/") -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    text = str(value).strip()
    if sep not in text:
        return None, None
    left, right = text.split(sep, 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None, None


def _stats_dict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(row.get("name") or "").strip().lower(): row.get("value")
        for row in rows
    }


def parse_passing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw = _stats_dict(rows)
    completions, attempts = _pair(raw.get("comp att"))
    sacks, sack_yards = _pair(raw.get("sacks"), sep="-")
    return {
        "completions": completions,
        "attempts": attempts,
        "yards": _num(raw.get("yards")),
        "yards_per_attempt": _num(raw.get("average")),
        "touchdowns": _num(raw.get("passing touch downs")),
        "interceptions": _num(raw.get("interceptions")),
        "sacks": sacks,
        "sack_yards": sack_yards,
        "rating": _num(raw.get("rating")),
        "two_point": _num(raw.get("two pt")),
    }


def parse_receiving(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw = _stats_dict(rows)
    return {
        "targets": _num(raw.get("targets")),
        "receptions": _num(raw.get("total receptions")),
        "yards": _num(raw.get("yards")),
        "yards_per_reception": _num(raw.get("average")),
        "touchdowns": _num(raw.get("receiving touch downs")),
        "longest_reception": _num(raw.get("longest reception")),
        "two_point": _num(raw.get("two pt")),
    }


def parse_rushing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw = _stats_dict(rows)
    return {
        "attempts": _num(raw.get("total rushes")),
        "yards": _num(raw.get("yards")),
        "yards_per_attempt": _num(raw.get("average")),
        "touchdowns": _num(raw.get("rushing touch downs")),
        "longest_rush": _num(raw.get("longest rush")),
        "two_point": _num(raw.get("two pt")),
    }


GROUP_PARSERS = {
    "passing": parse_passing,
    "receiving": parse_receiving,
    "rushing": parse_rushing,
}


def parse_player_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten API-Sports team/group/player payloads into player-game rows.

    Missing provider values remain None. A player absent from a group is not
    manufactured as a zero because absence can mean no participation or
    incomplete provider coverage.
    """
    players: dict[tuple[int, int], dict[str, Any]] = {}

    for team_row in rows:
        team = team_row.get("team") or {}
        team_id = int(team["id"])
        team_name = str(team.get("name") or team_id)

        for group in team_row.get("groups") or []:
            group_name = str(group.get("name") or "").strip().lower()
            parser = GROUP_PARSERS.get(group_name)
            if parser is None:
                continue

            for item in group.get("players") or []:
                player = item.get("player") or {}
                player_id = int(player["id"])
                key = (team_id, player_id)
                row = players.setdefault(
                    key,
                    {
                        "team_id": team_id,
                        "team_name": team_name,
                        "player_id": player_id,
                        "player_name": str(player.get("name") or player_id),
                        "passing": None,
                        "rushing": None,
                        "receiving": None,
                    },
                )
                row[group_name] = parser(item.get("statistics") or [])

    return list(players.values())


def parse_team_statistics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in rows:
        team = row.get("team") or {}
        stats = row.get("statistics") or {}

        passing = stats.get("passing") or {}
        rushing = stats.get("rushings") or {}
        plays = stats.get("plays") or {}
        yards = stats.get("yards") or {}
        turnovers = stats.get("turnovers") or {}
        sacks = stats.get("sacks") or {}
        possession = stats.get("posession") or stats.get("possession") or {}

        completions, attempts = _pair(passing.get("comp_att"))
        out.append(
            {
                "team_id": int(team["id"]),
                "team_name": str(team.get("name") or team["id"]),
                "plays": _num(plays.get("total")),
                "total_yards": _num(yards.get("total")),
                "yards_per_play": _num(yards.get("yards_per_play")),
                # API-Sports team passing yards may be net of sacks. Player
                # passing yards must come from the player statistics endpoint.
                "team_net_passing_yards": _num(passing.get("total")),
                "pass_completions": completions,
                "pass_attempts": attempts,
                "interceptions_thrown": _num(passing.get("interceptions_thrown")),
                "rushing_yards": _num(rushing.get("total")),
                "rush_attempts": _num(rushing.get("attempts")),
                "turnovers": _num(turnovers.get("total")),
                "sacks_made": _num(sacks.get("total")),
                "possession": possession.get("total"),
            }
        )

    return out

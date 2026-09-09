from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.config.nfl_2026 import NFL_LEAGUE_ID
from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import load_json, save_json
from nfl.ingest.statistics import parse_player_groups, parse_team_statistics

COMPLETED = {"FT", "AET"}


def parse_dt(row: dict[str, Any]) -> datetime:
    game = row.get("game") or row
    date_obj = game.get("date") or {}
    if isinstance(date_obj, dict):
        stamp = date_obj.get("timestamp")
        if stamp is not None:
            return datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        value = f"{date_obj.get('date')}T{date_obj.get('time') or '00:00'}"
        return datetime.fromisoformat(value)
    return datetime.fromisoformat(str(date_obj).replace("Z", "+00:00"))


def game_status(row: dict[str, Any]) -> str:
    game = row.get("game") or row
    status = game.get("status") or {}
    if isinstance(status, dict):
        return str(status.get("short") or "")
    return str(status)


def cached_games(
    client: APINFLClient,
    team_id: int,
    season: int,
) -> list[dict[str, Any]]:
    key = f"team_{team_id}_season_{season}"
    cached = load_json("game_lists", key)
    if cached is not None:
        return cached
    rows = client.games(
        league=NFL_LEAGUE_ID,
        season=season,
        team=team_id,
    ).response
    save_json("game_lists", key, rows)
    return rows


def cached_team_stats(client: APINFLClient, game_id: int) -> list[dict[str, Any]]:
    key = f"game_{game_id}"
    cached = load_json("team_stats", key)
    if cached is not None:
        return cached
    rows = client.team_game_statistics(game_id).response
    save_json("team_stats", key, rows)
    return rows


def cached_player_stats(client: APINFLClient, game_id: int) -> list[dict[str, Any]]:
    key = f"game_{game_id}"
    cached = load_json("player_stats", key)
    if cached is not None:
        return cached
    rows = client.player_game_statistics(game_id).response
    save_json("player_stats", key, rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill recent context for both teams in an upcoming NFL game."
    )
    parser.add_argument("--game", required=True, type=int)
    parser.add_argument("--matches", type=int, default=20)
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2026, 2025, 2024],
    )
    args = parser.parse_args()

    client = APINFLClient()
    target_rows = client.games(id=args.game).response
    if not target_rows:
        raise SystemExit(f"Game {args.game} not found.")

    target = target_rows[0]
    cutoff = parse_dt(target)
    teams = target.get("teams") or {}

    target_info = {
        "game_id": args.game,
        "cutoff": cutoff.isoformat(),
        "teams": teams,
        "histories": {},
    }

    for side in ("home", "away"):
        team = teams.get(side) or {}
        team_id = int(team["id"])
        team_name = str(team.get("name") or team_id)

        candidates: dict[int, dict[str, Any]] = {}
        for season in args.seasons:
            for row in cached_games(client, team_id, season):
                gid = int((row.get("game") or row).get("id") or row.get("id"))
                if game_status(row) not in COMPLETED:
                    continue
                if parse_dt(row) >= cutoff:
                    continue
                candidates[gid] = row

        ordered = sorted(candidates.values(), key=parse_dt)
        selected = ordered[-args.matches:]

        history = []
        print(f"{team_name}: {len(selected)} prior completed games")
        for idx, row in enumerate(selected, start=1):
            game = row.get("game") or row
            gid = int(game.get("id") or row.get("id"))
            team_rows = parse_team_statistics(cached_team_stats(client, gid))
            player_rows = parse_player_groups(cached_player_stats(client, gid))

            own_team = next(
                (x for x in team_rows if int(x["team_id"]) == team_id),
                None,
            )
            opponent_team = next(
                (x for x in team_rows if int(x["team_id"]) != team_id),
                None,
            )
            own_players = [
                x for x in player_rows if int(x["team_id"]) == team_id
            ]

            history.append(
                {
                    "game_id": gid,
                    "date": parse_dt(row).isoformat(),
                    "week": game.get("week"),
                    "stage": game.get("stage"),
                    "team": own_team,
                    "opponent_team": opponent_team,
                    "players": own_players,
                }
            )

            if idx % 5 == 0 or idx == len(selected):
                print(f"  stats {idx}/{len(selected)}")

        target_info["histories"][str(team_id)] = {
            "team_id": team_id,
            "team_name": team_name,
            "matches": history,
        }

    path = save_json("contexts", f"game_{args.game}", target_info)
    print(f"\nSaved context to {path}")


if __name__ == "__main__":
    main()

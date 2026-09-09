from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.config.nfl_2026 import NFL_LEAGUE_ID
from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import load_json, save_json
from nfl.ingest.statistics import parse_team_statistics
from nfl.model.evaluation import regression_metrics
from nfl.model.team_stats import project_team_stats

COMPLETED = {"FT", "AET"}
EXCLUDED_STAGE_TOKENS = {"pre season", "preseason"}


def parse_dt(row: dict[str, Any]) -> datetime:
    game = row.get("game") or row
    date_obj = game.get("date") or {}
    if isinstance(date_obj, dict):
        stamp = date_obj.get("timestamp")
        if stamp is not None:
            return datetime.fromtimestamp(int(stamp), tz=timezone.utc)
        value = f"{date_obj.get('date')}T{date_obj.get('time') or '00:00'}"
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(date_obj).replace("Z", "+00:00"))


def status(row: dict[str, Any]) -> str:
    game = row.get("game") or row
    value = game.get("status") or {}
    if isinstance(value, dict):
        return str(value.get("short") or "")
    return str(value)


def stage(row: dict[str, Any]) -> str:
    return str((row.get("game") or row).get("stage") or "").strip()


def stage_allowed(row: dict[str, Any]) -> bool:
    normalized = stage(row).casefold().replace("-", " ")
    return not any(token in normalized for token in EXCLUDED_STAGE_TOKENS)


def week_number(row: dict[str, Any]) -> int | None:
    raw = str((row.get("game") or row).get("week") or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return int(digits) if digits else None


def game_id(row: dict[str, Any]) -> int:
    game = row.get("game") or row
    return int(game.get("id") or row.get("id"))


def teams(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    value = row.get("teams") or {}
    return value.get("home") or {}, value.get("away") or {}


def cached_team_stats(client: APINFLClient, gid: int) -> list[dict[str, Any]]:
    key = f"game_{gid}"
    cached = load_json("team_stats", key)
    if cached is not None:
        return cached
    rows = client.team_game_statistics(gid).response
    save_json("team_stats", key, rows)
    return rows


def historical_row(
    fixture: dict[str, Any],
    team_id: int,
    parsed_stats: list[dict[str, Any]],
) -> dict[str, Any] | None:
    own = next((x for x in parsed_stats if int(x["team_id"]) == team_id), None)
    opp = next((x for x in parsed_stats if int(x["team_id"]) != team_id), None)
    if own is None or opp is None:
        return None
    game = fixture.get("game") or fixture
    return {
        "game_id": game_id(fixture),
        "date": parse_dt(fixture).isoformat(),
        "week": game.get("week"),
        "stage": game.get("stage"),
        "team": own,
        "opponent_team": opp,
        "players": [],
    }


def actual_value(
    stat: str,
    own: dict[str, Any],
    opp: dict[str, Any],
) -> float | None:
    if stat == "points":
        value = opp.get("points_against")
    else:
        mapping = {
            "plays": "plays",
            "pass_attempts": "pass_attempts",
            "completions": "pass_completions",
            "passing_yards": "team_net_passing_yards",
            "rush_attempts": "rush_attempts",
            "rushing_yards": "rushing_yards",
            "sacks": "sacks_made",
            "turnovers": "turnovers",
        }
        value = own.get(mapping[stat])
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def projection_value(stat: str, p: Any) -> float:
    return float(
        {
            "plays": p.expected_plays,
            "pass_attempts": p.expected_pass_attempts,
            "completions": p.expected_completions,
            "passing_yards": p.expected_passing_yards,
            "rush_attempts": p.expected_rush_attempts,
            "rushing_yards": p.expected_rushing_yards,
            "sacks": p.expected_sacks_made,
            "turnovers": p.expected_turnovers,
            "points": p.expected_points,
        }[stat]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Leakage-free walk-forward backtest for NFL team-stat projections."
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--history", type=int, default=20)
    parser.add_argument("--min-history", type=int, default=8)
    parser.add_argument("--half-life", type=float, default=8.0)
    parser.add_argument("--start-week", type=int, default=None)
    parser.add_argument("--end-week", type=int, default=None)
    parser.add_argument("--max-games", type=int, default=None)
    parser.add_argument(
        "--warmup-seasons",
        nargs="*",
        type=int,
        default=None,
        help=(
            "Prior seasons used only to seed pre-game history. "
            "Defaults to season-1. Pass no values to disable warmup."
        ),
    )
    args = parser.parse_args()

    client = APINFLClient()
    fixtures = client.games(league=NFL_LEAGUE_ID, season=args.season).response
    fixtures = [
        row for row in fixtures
        if status(row) in COMPLETED and stage_allowed(row)
    ]
    fixtures.sort(key=parse_dt)

    histories: dict[int, list[dict[str, Any]]] = defaultdict(list)
    records: list[dict[str, Any]] = []
    match_records: list[dict[str, Any]] = []
    tested_games = 0

    # Seed each team's history with prior-season games so Week 1 can be
    # evaluated without a cold-start gap. These fixtures all occur strictly
    # before the target season, so the leakage barrier is preserved.
    warmup_seasons = (
        [args.season - 1]
        if args.warmup_seasons is None
        else list(args.warmup_seasons)
    )
    warmup_rows = 0
    for warmup_season in warmup_seasons:
        prior = client.games(
            league=NFL_LEAGUE_ID,
            season=warmup_season,
        ).response
        prior = [
            row for row in prior
            if status(row) in COMPLETED and stage_allowed(row)
        ]
        prior.sort(key=parse_dt)

        print(
            f"warming history from {warmup_season}: "
            f"{len(prior)} completed non-preseason fixtures"
        )
        for fixture in prior:
            gid = game_id(fixture)
            parsed = parse_team_statistics(cached_team_stats(client, gid))
            if len(parsed) != 2:
                continue
            home, away = teams(fixture)
            for tid in (int(away["id"]), int(home["id"])):
                row = historical_row(fixture, tid, parsed)
                if row is not None:
                    histories[tid].append(row)
                    warmup_rows += 1

    if warmup_seasons:
        covered = sum(1 for rows in histories.values() if len(rows) >= args.min_history)
        print(
            f"warmup complete: team_rows={warmup_rows} | "
            f"teams_with_{args.min_history}+_games={covered}\n"
        )

    for idx, fixture in enumerate(fixtures, start=1):
        if args.max_games is not None and tested_games >= args.max_games:
            break

        gid = game_id(fixture)
        wk = week_number(fixture)

        stats_raw = cached_team_stats(client, gid)
        parsed = parse_team_statistics(stats_raw)
        if len(parsed) != 2:
            continue

        home, away = teams(fixture)
        team_ids = [int(away["id"]), int(home["id"])]

        should_test = True
        if args.start_week is not None and (wk is None or wk < args.start_week):
            should_test = False
        if args.end_week is not None and (wk is None or wk > args.end_week):
            should_test = False

        if should_test:
            enough = all(len(histories[tid]) >= args.min_history for tid in team_ids)
            if enough:
                fixture_records: list[dict[str, Any]] = []
                for tid in team_ids:
                    own_hist = histories[tid][-args.history:]
                    opp_tid = next(x for x in team_ids if x != tid)
                    opp_hist = histories[opp_tid][-args.history:]
                    own_stats = next(x for x in parsed if int(x["team_id"]) == tid)
                    opp_stats = next(x for x in parsed if int(x["team_id"]) != tid)

                    p = project_team_stats(
                        team_id=tid,
                        team_name=str(own_stats.get("team_name") or tid),
                        own_matches=own_hist,
                        opponent_matches=opp_hist,
                        half_life=args.half_life,
                    )
                    if p is None:
                        continue

                    record = {
                        "game_id": gid,
                        "date": parse_dt(fixture).isoformat(),
                        "week": wk,
                        "stage": stage(fixture),
                        "team_id": tid,
                        "team_name": own_stats.get("team_name"),
                        "predicted": {},
                        "actual": {},
                    }
                    for stat in (
                        "plays",
                        "pass_attempts",
                        "completions",
                        "passing_yards",
                        "rush_attempts",
                        "rushing_yards",
                        "sacks",
                        "turnovers",
                        "points",
                    ):
                        record["predicted"][stat] = projection_value(stat, p)
                        record["actual"][stat] = actual_value(stat, own_stats, opp_stats)
                    records.append(record)
                    fixture_records.append(record)

                if len(fixture_records) == 2:
                    match_record = {
                        "game_id": gid,
                        "date": parse_dt(fixture).isoformat(),
                        "week": wk,
                        "stage": stage(fixture),
                        "predicted": {},
                        "actual": {},
                    }
                    for stat in (
                        "plays",
                        "pass_attempts",
                        "completions",
                        "passing_yards",
                        "rush_attempts",
                        "rushing_yards",
                        "sacks",
                        "turnovers",
                        "points",
                    ):
                        pred_values = [
                            r["predicted"].get(stat)
                            for r in fixture_records
                        ]
                        actual_values = [
                            r["actual"].get(stat)
                            for r in fixture_records
                        ]
                        match_record["predicted"][stat] = (
                            sum(float(v) for v in pred_values)
                            if all(v is not None for v in pred_values)
                            else None
                        )
                        match_record["actual"][stat] = (
                            sum(float(v) for v in actual_values)
                            if all(v is not None for v in actual_values)
                            else None
                        )
                    match_records.append(match_record)

                tested_games += 1

        # Only after pricing the target game do we append it to each team's history.
        # This is the leakage barrier.
        for tid in team_ids:
            row = historical_row(fixture, tid, parsed)
            if row is not None:
                histories[tid].append(row)

        if idx % 25 == 0:
            print(
                f"processed {idx}/{len(fixtures)} fixtures | "
                f"tested_games={tested_games} | team_rows={len(records)}"
            )

    if not records:
        raise SystemExit(
            "No test rows produced. Lower --min-history or widen the week range."
        )

    metrics = {}
    for stat in (
        "plays",
        "pass_attempts",
        "completions",
        "passing_yards",
        "rush_attempts",
        "rushing_yards",
        "sacks",
        "turnovers",
        "points",
    ):
        pred = [r["predicted"][stat] for r in records]
        actual = [r["actual"][stat] for r in records]
        pairs = [(p, a) for p, a in zip(pred, actual) if p is not None and a is not None]
        if not pairs:
            continue
        m = regression_metrics(
            [p for p, _ in pairs],
            [a for _, a in pairs],
        )
        metrics[stat] = m.to_dict()

    match_metrics = {}
    for stat in (
        "plays",
        "pass_attempts",
        "completions",
        "passing_yards",
        "rush_attempts",
        "rushing_yards",
        "sacks",
        "turnovers",
        "points",
    ):
        pred = [r["predicted"][stat] for r in match_records]
        actual = [r["actual"][stat] for r in match_records]
        pairs = [
            (p, a)
            for p, a in zip(pred, actual)
            if p is not None and a is not None
        ]
        if not pairs:
            continue
        m = regression_metrics(
            [p for p, _ in pairs],
            [a for _, a in pairs],
        )
        match_metrics[stat] = m.to_dict()

    print(
        f"\nNFL EDGE TEAM STATS WALK-FORWARD | season {args.season} | "
        f"games={tested_games} | team_rows={len(records)}"
    )
    print("No future fixtures are used in any projection.\n")
    print(f"{'STAT':20s} {'N':>5s} {'MAE':>9s} {'RMSE':>9s} {'BIAS':>9s}")
    print("-" * 56)
    for stat, m in metrics.items():
        print(
            f"{stat:20s} {m['n']:5d} "
            f"{m['mae']:9.2f} {m['rmse']:9.2f} {m['bias']:9.2f}"
        )

    if match_metrics:
        print("\nMATCH TOTAL METRICS")
        print(f"{'STAT':20s} {'N':>5s} {'MAE':>9s} {'RMSE':>9s} {'BIAS':>9s}")
        print("-" * 56)
        for stat, m in match_metrics.items():
            print(
                f"{stat:20s} {m['n']:5d} "
                f"{m['mae']:9.2f} {m['rmse']:9.2f} {m['bias']:9.2f}"
            )

    payload = {
        "season": args.season,
        "history": args.history,
        "min_history": args.min_history,
        "half_life": args.half_life,
        "start_week": args.start_week,
        "end_week": args.end_week,
        "warmup_seasons": warmup_seasons,
        "tested_games": tested_games,
        "team_rows": len(records),
        "match_rows": len(match_records),
        "metrics": metrics,
        "match_metrics": match_metrics,
        "records": records,
        "match_records": match_records,
    }
    key = (
        f"team_stats_{args.season}_h{args.history}_"
        f"hl{str(args.half_life).replace('.', 'p')}_"
        f"warm{'-'.join(str(x) for x in warmup_seasons) or 'none'}"
    )
    path = save_json("backtests", key, payload)
    print(f"\nSaved backtest to {path}")


if __name__ == "__main__":
    main()

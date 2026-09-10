from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.api_football import APIFootballClient
from ingest.statistics import fixture_statistics
from model.settlement import pnl_for_settlement, settle_handicap, settle_total

UCL_LEAGUE_ID = 2
FINAL_STATUSES = {"FT", "AET", "PEN"}
LEDGER_PATH = ROOT / "tracking" / "ucl_picks.json"
RESULTS_PATH = ROOT / "tracking" / "ucl_results.json"


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch.lower() for ch in text if ch.isalnum())


def fixture_matches(row: dict[str, Any], pick: dict[str, Any]) -> bool:
    teams = row.get("teams", {})
    return (
        normalize_name(str(teams.get("home", {}).get("name") or ""))
        == normalize_name(str(pick["home"]))
        and normalize_name(str(teams.get("away", {}).get("name") or ""))
        == normalize_name(str(pick["away"]))
    )


def load_ledger(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload.get("picks"), list):
        raise SystemExit(f"Invalid ledger: {path}")
    return payload


def fixture_row_for_pick(
    client: APIFootballClient,
    pick: dict[str, Any],
    date_cache: dict[str, list[dict[str, Any]]],
    id_cache: dict[int, dict[str, Any]],
    season: int,
) -> dict[str, Any] | None:
    fixture_id = pick.get("fixture_id")
    if fixture_id is not None:
        fixture_id = int(fixture_id)
        if fixture_id not in id_cache:
            rows = client.fixtures(id=fixture_id).response
            if rows:
                id_cache[fixture_id] = rows[0]
        return id_cache.get(fixture_id)

    match_date = str(pick["date"])
    if match_date not in date_cache:
        date_cache[match_date] = client.fixtures(
            league=UCL_LEAGUE_ID,
            season=season,
            date=match_date,
        ).response

    candidates = [row for row in date_cache[match_date] if fixture_matches(row, pick)]
    if len(candidates) == 1:
        return candidates[0]
    return None


def settle_pick(
    pick: dict[str, Any],
    fixture_row: dict[str, Any],
    stats_cache: dict[int, dict[int, dict[str, float | None]]],
    client: APIFootballClient,
) -> dict[str, Any]:
    row = dict(pick)
    fixture = fixture_row.get("fixture", {})
    teams = fixture_row.get("teams", {})
    fixture_id = int(fixture.get("id"))
    status = str(fixture.get("status", {}).get("short") or "")

    row["resolved_fixture_id"] = fixture_id
    row["fixture_status"] = status

    if status not in FINAL_STATUSES:
        row["result"] = "PENDING"
        row["reason"] = f"fixture status {status or 'unknown'}"
        return row

    if fixture_id not in stats_cache:
        stats_cache[fixture_id] = fixture_statistics(client, fixture_id)
    stats = stats_cache[fixture_id]

    side = str(pick["side"]).lower()
    if side not in {"home", "away"}:
        row["result"] = "ERROR"
        row["reason"] = f"invalid side {side}"
        return row

    opponent_side = "away" if side == "home" else "home"
    selected_id = int(teams[side]["id"])
    opponent_id = int(teams[opponent_side]["id"])
    stat = str(pick["stat"])

    selected_actual = stats.get(selected_id, {}).get(stat)
    opponent_actual = stats.get(opponent_id, {}).get(stat)
    row["actual"] = selected_actual
    row["opponent_actual"] = opponent_actual

    if selected_actual is None:
        row["result"] = "ERROR"
        row["reason"] = f"missing {stat} for selected team"
        return row

    market_type = str(pick["market_type"])
    line = float(pick["line"])
    if market_type == "team_total":
        settlement = settle_total(
            float(selected_actual), str(pick["selection"]), line
        )
    elif market_type == "handicap":
        if opponent_actual is None:
            row["result"] = "ERROR"
            row["reason"] = f"missing {stat} for opponent"
            return row
        settlement = settle_handicap(
            float(selected_actual), float(opponent_actual), line
        )
    else:
        row["result"] = "ERROR"
        row["reason"] = f"unsupported market type {market_type}"
        return row

    row["result"] = settlement.result
    row["win_stake"] = settlement.win_stake
    row["push_stake"] = settlement.push_stake
    row["loss_stake"] = settlement.loss_stake
    row["reference_pnl"] = pnl_for_settlement(
        settlement, pick.get("reference_odds")
    )

    model_mean = pick.get("model_mean")
    if model_mean is not None and market_type == "team_total":
        row["model_error"] = float(selected_actual) - float(model_mean)
        row["abs_model_error"] = abs(row["model_error"])
    return row


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [
        r for r in records if r.get("result") in {"W", "L", "P", "HW", "HL", "MIXED"}
    ]
    wins = sum(float(r.get("win_stake", 0.0)) for r in settled)
    pushes = sum(float(r.get("push_stake", 0.0)) for r in settled)
    losses = sum(float(r.get("loss_stake", 0.0)) for r in settled)
    decisions = wins + losses

    pnl_rows = [r for r in settled if r.get("reference_pnl") is not None]
    pnl = sum(float(r["reference_pnl"]) for r in pnl_rows)

    error_rows = [r for r in settled if r.get("model_error") is not None]
    mae = (
        sum(float(r["abs_model_error"]) for r in error_rows) / len(error_rows)
        if error_rows
        else None
    )
    bias = (
        sum(float(r["model_error"]) for r in error_rows) / len(error_rows)
        if error_rows
        else None
    )

    return {
        "picks": len(settled),
        "win_equivalent": round(wins, 4),
        "push_equivalent": round(pushes, 4),
        "loss_equivalent": round(losses, 4),
        "hit_rate": None if decisions <= 0 else wins / decisions,
        "reference_pnl_units": round(pnl, 4) if pnl_rows else None,
        "reference_roi": None if not pnl_rows else pnl / len(pnl_rows),
        "model_mae": mae,
        "model_bias": bias,
    }


def grouped_summary(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[str(row.get(key) or "UNKNOWN")].append(row)
    return {name: summary(rows) for name, rows in sorted(groups.items())}


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def num(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}"


def print_records(records: list[dict[str, Any]]) -> None:
    print("\nUCL PICK SETTLEMENT")
    print("=" * 104)
    print(f"{'DATE':10s} {'RESULT':7s} {'MATCH':31s} {'PICK':39s} {'ACTUAL':>7s}")
    print("-" * 104)
    for r in records:
        match = f"{r['home']} vs {r['away']}"[:31]
        if r["market_type"] == "team_total":
            pick_text = f"{r['team']} {r['selection'].upper()} {r['line']:g} {r['stat']}"
        else:
            pick_text = f"{r['team']} {float(r['line']):+g} {r['stat']} AH"
        actual = r.get("actual")
        actual_text = "—" if actual is None else f"{float(actual):g}"
        print(
            f"{r['date']:10s} {str(r.get('result','?')):7s} {match:31s} "
            f"{pick_text[:39]:39s} {actual_text:>7s}"
        )


def print_summary(title: str, metrics: dict[str, Any]) -> None:
    print(f"\n{title}")
    print("-" * 72)
    print(
        f"picks={metrics['picks']} | hit={pct(metrics['hit_rate'])} | "
        f"W-eq={metrics['win_equivalent']:g} | L-eq={metrics['loss_equivalent']:g} | "
        f"P-eq={metrics['push_equivalent']:g} | "
        f"ref P&L={num(metrics['reference_pnl_units'])}u | "
        f"ref ROI={pct(metrics['reference_roi'])}"
    )
    if metrics.get("model_mae") is not None:
        print(
            f"model MAE={metrics['model_mae']:.2f} | "
            f"model bias={metrics['model_bias']:+.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Settle the immutable UCL pick ledger and report hit rate/ROI by market."
    )
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--output", type=Path, default=RESULTS_PATH)
    parser.add_argument("--through", help="Only settle picks on or before YYYY-MM-DD")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    ledger = load_ledger(args.ledger)
    picks = list(ledger["picks"])
    if args.through:
        picks = [p for p in picks if str(p["date"]) <= args.through]

    client = APIFootballClient()
    date_cache: dict[str, list[dict[str, Any]]] = {}
    id_cache: dict[int, dict[str, Any]] = {}
    stats_cache: dict[int, dict[int, dict[str, float | None]]] = {}
    records: list[dict[str, Any]] = []

    for pick in picks:
        fixture_row = fixture_row_for_pick(
            client, pick, date_cache, id_cache, args.season
        )
        if fixture_row is None:
            row = dict(pick)
            row["result"] = "ERROR"
            row["reason"] = "fixture not resolved uniquely"
            records.append(row)
            continue
        records.append(settle_pick(pick, fixture_row, stats_cache, client))

    official = [r for r in records if r.get("count_in_official", False)]
    experimental = [r for r in records if not r.get("count_in_official", False)]

    print_records(records)
    overall = summary(official)
    print_summary("OFFICIAL STRAIGHTS", overall)

    print("\nBY DATE")
    for name, metrics in grouped_summary(official, "date").items():
        print(f"  {name}: n={metrics['picks']:2d} | hit={pct(metrics['hit_rate']):>6s} | ref ROI={pct(metrics['reference_roi']):>7s}")

    print("\nBY STAT MARKET")
    by_stat = grouped_summary(official, "stat")
    for name, metrics in sorted(
        by_stat.items(),
        key=lambda item: (item[1]["hit_rate"] is not None, item[1]["hit_rate"] or -1),
        reverse=True,
    ):
        print(
            f"  {name:18s} n={metrics['picks']:2d} | "
            f"hit={pct(metrics['hit_rate']):>6s} | ref ROI={pct(metrics['reference_roi']):>7s} | "
            f"MAE={'—' if metrics['model_mae'] is None else f'{metrics['model_mae']:.2f}'}"
        )

    if experimental:
        print_summary("EXPERIMENTAL / LATE ADDS (NOT IN OFFICIAL HIT RATE)", summary(experimental))

    payload = {
        "meta": {
            "version": "ucl-pick-results-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "API-Football fixture statistics",
            "reference_roi_note": "Uses published reference snapshot odds, not confirmed wager fills.",
        },
        "overall_official": overall,
        "by_date": grouped_summary(official, "date"),
        "by_stat": by_stat,
        "by_market_type": grouped_summary(official, "market_type"),
        "by_reliability": grouped_summary(official, "reliability"),
        "experimental": summary(experimental),
        "records": records,
    }

    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nSaved canonical tracker output to {args.output}")


if __name__ == "__main__":
    main()

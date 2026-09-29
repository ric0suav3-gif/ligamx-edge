from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from today_edge.model import (  # noqa: E402
    blend_probabilities,
    consensus,
    devig,
    expected_value,
    grade_pick,
    match_probabilities,
    project_goals,
    settle,
)


BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_TIMEZONE = "America/Mexico_City"
FINAL_STATUSES = {"FT", "AET", "PEN"}
PREGAME_STATUSES = {"NS", "TBD"}
SELECTION_LABELS = {
    "DRAW": "Empate",
    "OVER_2_5": "Más de 2.5 goles",
    "UNDER_2_5": "Menos de 2.5 goles",
    "BTTS_YES": "Ambos anotan — Sí",
    "BTTS_NO": "Ambos anotan — No",
}


class APIFootballError(RuntimeError):
    pass


def local_timezone(name: str):
    """Resolve an IANA zone, with a Windows-safe Mexico City fallback."""
    try:
        return ZoneInfo(name)
    except Exception:
        if name == DEFAULT_TIMEZONE:
            # Mexico City has observed permanent UTC-6 since October 2022.
            return timezone(timedelta(hours=-6), name="CST")
        raise


class APIFootballClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.last_request = 0.0
        self.request_count = 0

    def get(self, endpoint: str, **params: Any) -> Any:
        elapsed = time.monotonic() - self.last_request
        if elapsed < 0.35:
            time.sleep(0.35 - elapsed)
        response: requests.Response | None = None
        for attempt in range(4):
            self.last_request = time.monotonic()
            response = self.session.get(
                f"{self.base_url}/{endpoint.lstrip('/')}",
                params={key: value for key, value in params.items() if value is not None},
                headers={"x-apisports-key": self.api_key},
                timeout=40,
            )
            self.request_count += 1
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            time.sleep(min(20.0, 2.0 ** (attempt + 1)))
        if response is None:
            raise APIFootballError(f"No response from {endpoint}")
        if response.status_code >= 400:
            raise APIFootballError(f"HTTP {response.status_code} from {endpoint}")
        payload = response.json()
        if payload.get("errors"):
            raise APIFootballError(f"API-Football error from {endpoint}: {payload['errors']}")
        return payload.get("response", [])


def parse_env_file(path: Path) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if line.startswith("API_FOOTBALL_KEY="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            return value or None
    return None


def load_api_key(explicit_env_file: Path | None) -> tuple[str, str]:
    direct = os.getenv("API_FOOTBALL_KEY")
    if direct:
        return direct.strip(), "environment"
    candidates = []
    if explicit_env_file:
        candidates.append(explicit_env_file)
    candidates.extend(
        [
            ROOT / ".env",
            Path.home() / "Downloads" / "env file.txt",
            Path.home() / "Downloads" / "env",
        ]
    )
    for path in candidates:
        value = parse_env_file(path)
        if value:
            return value, str(path)
    raise SystemExit("Missing API_FOOTBALL_KEY. Add it to .env or pass --env-file.")


def iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fixture_sort_key(item: dict[str, Any]) -> datetime:
    return iso_datetime(item["fixture"]["date"])


def parse_team_history(
    rows: Iterable[dict[str, Any]], team_id: int, before: datetime, limit: int = 10
) -> list[tuple[float, float]]:
    history: list[tuple[datetime, float, float]] = []
    for row in rows:
        fixture = row.get("fixture", {})
        if fixture.get("status", {}).get("short") not in FINAL_STATUSES:
            continue
        played_at = iso_datetime(fixture["date"])
        if played_at >= before:
            continue
        goals = row.get("goals", {})
        teams = row.get("teams", {})
        home_id = int(teams.get("home", {}).get("id") or 0)
        away_id = int(teams.get("away", {}).get("id") or 0)
        if goals.get("home") is None or goals.get("away") is None:
            continue
        if team_id == home_id:
            goals_for, goals_against = goals["home"], goals["away"]
        elif team_id == away_id:
            goals_for, goals_against = goals["away"], goals["home"]
        else:
            continue
        history.append((played_at, float(goals_for), float(goals_against)))
    history.sort(key=lambda row: row[0])
    return [(row[1], row[2]) for row in history[-limit:]]


def value_map(values: Iterable[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in values:
        try:
            out[str(row.get("value", "")).strip().lower()] = float(row["odd"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def complete_book_market(bookmaker: dict[str, Any], bet_id: int) -> dict[str, float] | None:
    bet = next((row for row in bookmaker.get("bets", []) if int(row.get("id", -1)) == bet_id), None)
    if not bet:
        return None
    values = value_map(bet.get("values", []))
    if bet_id == 1:
        aliases = {"HOME": "home", "DRAW": "draw", "AWAY": "away"}
    elif bet_id == 5:
        aliases = {"OVER_2_5": "over 2.5", "UNDER_2_5": "under 2.5"}
    elif bet_id == 8:
        aliases = {"BTTS_YES": "yes", "BTTS_NO": "no"}
    else:
        return None
    if not all(alias in values for alias in aliases.values()):
        return None
    return {selection: values[alias] for selection, alias in aliases.items()}


def aggregate_odds(raw_odds: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    if not raw_odds:
        return {}
    bookmakers = raw_odds[0].get("bookmakers", [])
    market_specs = {"1X2": 1, "TOTAL_2_5": 5, "BTTS": 8}
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for market_name, bet_id in market_specs.items():
        by_selection: dict[str, list[dict[str, Any]]] = {}
        for bookmaker in bookmakers:
            prices = complete_book_market(bookmaker, bet_id)
            if not prices:
                continue
            try:
                fair = devig(prices)
            except ValueError:
                continue
            for selection, price in prices.items():
                by_selection.setdefault(selection, []).append(
                    {
                        "book": bookmaker.get("name", "Unknown"),
                        "odds": price,
                        "probability": fair[selection],
                    }
                )
        if not by_selection:
            continue
        result[market_name] = {}
        for selection, quotes in by_selection.items():
            probability, disagreement = consensus(row["probability"] for row in quotes)
            best = max(quotes, key=lambda row: row["odds"])
            result[market_name][selection] = {
                "probability": probability,
                "disagreement": disagreement,
                "books": len(quotes),
                "median_odds": float(statistics.median(row["odds"] for row in quotes)),
                "best_odds": float(best["odds"]),
                "best_book": best["book"],
                "quotes": quotes,
            }
    return result


def api_probabilities(prediction: dict[str, Any] | None) -> dict[str, float]:
    if not prediction:
        return {}
    raw = prediction.get("predictions", {}).get("percent", {})
    values: dict[str, float] = {}
    for selection, api_name in (("HOME", "home"), ("DRAW", "draw"), ("AWAY", "away")):
        value = str(raw.get(api_name, "0")).replace("%", "").strip()
        try:
            values[selection] = float(value) / 100.0
        except ValueError:
            return {}
    total = sum(values.values())
    return {key: value / total for key, value in values.items()} if total else {}


def selection_label(selection: str, home: str, away: str) -> str:
    if selection == "HOME":
        return home
    if selection == "AWAY":
        return away
    return SELECTION_LABELS.get(selection, selection)


def build_candidates(
    markets: dict[str, dict[str, dict[str, Any]]],
    poisson: dict[str, float],
    api_model: dict[str, float],
    home: str,
    away: str,
    minimum_samples: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    model_groups = {
        "1X2": {key: poisson[key] for key in ("HOME", "DRAW", "AWAY")},
        "TOTAL_2_5": {key: poisson[key] for key in ("OVER_2_5", "UNDER_2_5")},
        "BTTS": {key: poisson[key] for key in ("BTTS_YES", "BTTS_NO")},
    }
    for market_name, quotes_by_selection in markets.items():
        if market_name not in model_groups:
            continue
        market_probs = {
            key: row["probability"] for key, row in quotes_by_selection.items()
        }
        if set(market_probs) != set(model_groups[market_name]):
            continue
        if market_name == "1X2":
            # API-Football's competition sample is one match on this slate, so
            # its opaque prediction remains a small corroborating signal only.
            blended = blend_probabilities(
                market_probs,
                model_groups[market_name],
                api_model,
                market_weight=0.77,
                model_weight=0.20,
                api_weight=0.03,
            )
        else:
            blended = blend_probabilities(
                market_probs,
                model_groups[market_name],
                market_weight=0.80,
                model_weight=0.20,
                api_weight=0.0,
            )
        for selection, quote in quotes_by_selection.items():
            probability = blended[selection]
            edge = expected_value(probability, quote["best_odds"])
            median_edge = expected_value(probability, quote["median_odds"])
            stable_best_price = quote["best_odds"] <= quote["median_odds"] * 1.12
            grade = grade_pick(edge, quote["books"], quote["disagreement"])
            eligible = (
                minimum_samples >= 6
                and quote["books"] >= 4
                and 1.35 <= quote["best_odds"] <= 3.00
                and probability >= 0.36
                and edge >= 0.025
                and median_edge >= -0.025
                and quote["disagreement"] <= 0.08
                and stable_best_price
                and grade in {"A", "B"}
            )
            candidates.append(
                {
                    "market": market_name,
                    "selection": selection,
                    "label": selection_label(selection, home, away),
                    "probability": probability,
                    "fair_odds": 1.0 / probability,
                    "best_odds": quote["best_odds"],
                    "median_odds": quote["median_odds"],
                    "best_book": quote["best_book"],
                    "books": quote["books"],
                    "disagreement": quote["disagreement"],
                    "edge": edge,
                    "median_edge": median_edge,
                    "eligible": eligible,
                    "grade": grade,
                    "score": edge - 0.65 * quote["disagreement"] + min(quote["books"], 10) * 0.002,
                }
            )
    return sorted(candidates, key=lambda row: row["score"], reverse=True)


def public_fixture(row: dict[str, Any]) -> dict[str, Any]:
    fixture = row["fixture"]
    league = row["league"]
    teams = row["teams"]
    return {
        "id": int(fixture["id"]),
        "date": fixture["date"],
        "timestamp": fixture["timestamp"],
        "status": fixture["status"]["short"],
        "status_long": fixture["status"]["long"],
        "venue": (fixture.get("venue") or {}).get("name"),
        "league": {
            "id": league["id"],
            "name": league["name"],
            "country": league["country"],
            "round": league.get("round"),
            "logo": league.get("logo"),
            "flag": league.get("flag"),
        },
        "home": {
            "id": teams["home"]["id"],
            "name": teams["home"]["name"],
            "logo": teams["home"]["logo"],
        },
        "away": {
            "id": teams["away"]["id"],
            "name": teams["away"]["name"],
            "logo": teams["away"]["logo"],
        },
        "goals": row.get("goals"),
    }


def settle_tracking(client: APIFootballClient, tracking: dict[str, Any]) -> None:
    fixture_cache: dict[int, dict[str, Any] | None] = {}
    for pick in tracking.get("picks", []):
        if pick.get("result") in {"WIN", "LOSS", "PUSH"}:
            continue
        fixture_id = int(pick["fixture_id"])
        if fixture_id not in fixture_cache:
            rows = client.get("fixtures", id=fixture_id)
            fixture_cache[fixture_id] = rows[0] if rows else None
        fixture = fixture_cache[fixture_id]
        if not fixture or fixture["fixture"]["status"]["short"] not in FINAL_STATUSES:
            continue
        home_goals = fixture.get("goals", {}).get("home")
        away_goals = fixture.get("goals", {}).get("away")
        if home_goals is None or away_goals is None:
            continue
        pick["home_goals"] = int(home_goals)
        pick["away_goals"] = int(away_goals)
        pick["result"] = settle(
            pick["market"], pick["selection"], int(home_goals), int(away_goals)
        )
        pick["graded_at"] = datetime.now(timezone.utc).isoformat()


def tracking_summary(tracking: dict[str, Any]) -> dict[str, Any]:
    graded = [row for row in tracking.get("picks", []) if row.get("result") in {"WIN", "LOSS", "PUSH"}]
    wins = sum(row["result"] == "WIN" for row in graded)
    losses = sum(row["result"] == "LOSS" for row in graded)
    pushes = sum(row["result"] == "PUSH" for row in graded)
    profit = sum(
        (row["opening_odds"] - 1.0) if row["result"] == "WIN" else -1.0 if row["result"] == "LOSS" else 0.0
        for row in graded
    )
    clv_rows = [row["clv"] for row in tracking.get("picks", []) if row.get("clv") is not None]
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": sum(row.get("result") == "PENDING" for row in tracking.get("picks", [])),
        "profit_units": profit,
        "roi": profit / len(graded) if graded else None,
        "average_clv": statistics.mean(clv_rows) if clv_rows else None,
    }


def upsert_tracking(
    tracking: dict[str, Any], fixtures: list[dict[str, Any]], official_picks: list[dict[str, Any]], now: datetime
) -> None:
    indexed = {row["id"]: row for row in tracking.setdefault("picks", [])}
    fixtures_by_id = {int(row["id"]): row for row in fixtures}
    for pick in official_picks:
        fixture = fixtures_by_id[int(pick["fixture_id"])]
        pick_id = f"{pick['date']}:{pick['fixture_id']}:{pick['market']}:{pick['selection']}"
        existing = indexed.get(pick_id)
        if existing is None:
            existing = {
                "id": pick_id,
                "date": pick["date"],
                "fixture_id": pick["fixture_id"],
                "match": pick["match"],
                "market": pick["market"],
                "selection": pick["selection"],
                "label": pick["label"],
                "grade": pick["grade"],
                "opening_odds": pick["best_odds"],
                "opening_book": pick["best_book"],
                "closing_odds": pick["best_odds"],
                "closing_book": pick["best_book"],
                "clv": None,
                "result": "PENDING",
                "published_at": now.isoformat(),
                "kickoff": fixture["date"],
            }
            tracking["picks"].append(existing)
            indexed[pick_id] = existing
        kickoff = iso_datetime(fixture["date"])
        if now.astimezone(timezone.utc) < kickoff.astimezone(timezone.utc):
            existing["closing_odds"] = pick["best_odds"]
            existing["closing_book"] = pick["best_book"]
            existing["clv"] = existing["opening_odds"] / existing["closing_odds"] - 1.0
            existing["last_price_at"] = now.isoformat()


def build_payload(
    client: APIFootballClient,
    match_date: str,
    timezone_name: str,
    league_id: int,
    top_picks: int,
    tracking_path: Path,
) -> dict[str, Any]:
    now = datetime.now(local_timezone(timezone_name))
    all_today = client.get("fixtures", date=match_date, timezone=timezone_name)
    league_rows = [row for row in all_today if int(row["league"]["id"]) == league_id]
    if not league_rows:
        raise SystemExit(f"No league {league_id} fixtures found on {match_date}.")

    pregame_rows = [row for row in league_rows if row["fixture"]["status"]["short"] in PREGAME_STATUSES]
    history_cache: dict[int, list[dict[str, Any]]] = {}
    team_ids = {
        int(team["id"])
        for row in pregame_rows
        for team in (row["teams"]["home"], row["teams"]["away"])
    }
    for team_id in sorted(team_ids):
        history_cache[team_id] = client.get("fixtures", team=team_id, last=14)

    public_rows: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    baseline_goals_values: list[float] = []
    for team_id, rows in history_cache.items():
        for goals_for, _ in parse_team_history(rows, team_id, now, limit=10):
            baseline_goals_values.append(goals_for)
    baseline_goals = statistics.mean(baseline_goals_values) if baseline_goals_values else 1.32
    baseline_goals = min(max(baseline_goals, 1.05), 1.60)

    for raw in sorted(league_rows, key=fixture_sort_key):
        row = public_fixture(raw)
        row["recommendation"] = None
        row["alternatives"] = []
        if row["status"] not in PREGAME_STATUSES:
            row["screen"] = "IN_PLAY_OR_FINAL"
            public_rows.append(row)
            continue

        kickoff = iso_datetime(row["date"])
        home_history = parse_team_history(history_cache[row["home"]["id"]], row["home"]["id"], kickoff)
        away_history = parse_team_history(history_cache[row["away"]["id"]], row["away"]["id"], kickoff)
        minimum_samples = min(len(home_history), len(away_history))
        if not home_history or not away_history:
            row["screen"] = "INSUFFICIENT_HISTORY"
            public_rows.append(row)
            continue

        projection = project_goals(
            home_history,
            away_history,
            baseline_goals=baseline_goals,
            prior_matches=7.0,
        )
        poisson = match_probabilities(projection.home_xg, projection.away_xg)
        odds_response = client.get("odds", fixture=row["id"])
        markets = aggregate_odds(odds_response)
        prediction_response = client.get("predictions", fixture=row["id"])
        prediction = prediction_response[0] if prediction_response else None
        api_model = api_probabilities(prediction)
        candidates = build_candidates(
            markets,
            poisson,
            api_model,
            row["home"]["name"],
            row["away"]["name"],
            minimum_samples,
        )
        eligible = [candidate for candidate in candidates if candidate["eligible"]]
        row["screen"] = "PASS" if eligible else "NO_BET"
        row["projection"] = {
            "home_xg": projection.home_xg,
            "away_xg": projection.away_xg,
            "home_samples": projection.home_samples,
            "away_samples": projection.away_samples,
            "baseline_goals": baseline_goals,
            "poisson": poisson,
            "api_1x2": api_model,
            "api_advice": (prediction or {}).get("predictions", {}).get("advice"),
        }
        row["market_coverage"] = {
            market: max((quote["books"] for quote in selections.values()), default=0)
            for market, selections in markets.items()
        }
        row["recommendation"] = eligible[0] if eligible else None
        row["alternatives"] = candidates[:3]
        for candidate in eligible[:1]:
            candidate.update(
                {
                    "fixture_id": row["id"],
                    "date": match_date,
                    "kickoff": row["date"],
                    "match": f"{row['home']['name']} vs {row['away']['name']}",
                    "home": row["home"]["name"],
                    "away": row["away"]["name"],
                }
            )
            all_candidates.append(candidate)
        public_rows.append(row)

    official_picks = sorted(all_candidates, key=lambda row: row["score"], reverse=True)[:top_picks]
    tracking = {"version": 1, "picks": []}
    if tracking_path.exists():
        tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
    settle_tracking(client, tracking)
    upsert_tracking(tracking, public_rows, official_picks, now)
    tracking["updated_at"] = now.isoformat()
    tracking_path.parent.mkdir(parents=True, exist_ok=True)
    tracking_path.write_text(json.dumps(tracking, ensure_ascii=False, indent=2), encoding="utf-8")

    status_counts: dict[str, int] = {}
    for row in public_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    return {
        "meta": {
            "title": "Today Edge",
            "date": match_date,
            "timezone": timezone_name,
            "generated_at": now.isoformat(),
            "api_connected": True,
            "api_requests": client.request_count,
            "league_id": league_id,
            "method": "API-Football fixtures + multi-book de-vigged prices, shrunk 77–80% toward market consensus with a 20% recency-weighted Poisson signal and a maximum 3% API prediction signal.",
            "guardrail": "Pregame only. Minimum six completed matches per team, four bookmakers, stable price, and at least 2.5% expected value at the best listed book.",
            "status_counts": status_counts,
            "baseline_goals": baseline_goals,
        },
        "league": public_rows[0]["league"],
        "fixtures": public_rows,
        "picks": official_picks,
        "tracking": {
            "summary": tracking_summary(tracking),
            "picks": sorted(tracking.get("picks", []), key=lambda row: row["published_at"], reverse=True),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a self-contained API-Football Today Edge card.")
    parser.add_argument("--date", default=None, help="Slate date in YYYY-MM-DD; defaults to today in --timezone.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--league", type=int, default=5, help="API-Football league id (default: UEFA Nations League).")
    parser.add_argument("--top", type=int, default=3, help="Maximum published straight picks.")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--template", type=Path, default=ROOT / "web" / "today_edge_template.html")
    parser.add_argument("--output", type=Path, default=ROOT / "today-edge.html")
    parser.add_argument("--snapshot", type=Path, default=None)
    args = parser.parse_args()

    match_date = args.date or datetime.now(local_timezone(args.timezone)).date().isoformat()
    api_key, _key_source = load_api_key(args.env_file)
    base_url = os.getenv("API_FOOTBALL_BASE_URL", BASE_URL)
    client = APIFootballClient(api_key, base_url)
    payload = build_payload(
        client,
        match_date,
        args.timezone,
        args.league,
        args.top,
        ROOT / "tracking" / "today_edge_picks.json",
    )
    snapshot_path = args.snapshot or ROOT / "data" / f"today_edge_{match_date}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    template = args.template.read_text(encoding="utf-8")
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = template.replace("__TODAY_EDGE_DATA__", blob)
    if "__TODAY_EDGE_DATA__" in html:
        raise SystemExit("Template data placeholder was not replaced.")
    args.output.write_text(html, encoding="utf-8")

    print(f"Built: {args.output}")
    print(f"Snapshot: {snapshot_path}")
    print(f"API connected: yes | requests this build: {client.request_count}")
    print(f"Fixtures: {len(payload['fixtures'])} | published picks: {len(payload['picks'])}")
    for index, pick in enumerate(payload["picks"], 1):
        print(
            f"{index}. {pick['match']} — {pick['label']} @ {pick['best_odds']:.2f} "
            f"({pick['best_book']}) | p={pick['probability']:.1%} EV={pick['edge']:.1%} | {pick['grade']}"
        )


if __name__ == "__main__":
    main()

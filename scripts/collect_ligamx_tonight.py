from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from ingest.statistics import parse_fixture_statistics
from model.dispersion import fit_count_distribution

TZ_NAME = "America/Mexico_City"
COMPLETED = {"FT", "AET", "PEN"}
MODEL_STATS = (
    "shots",
    "shots_on_target",
    "corners",
    "fouls",
    "yellow",
    "red",
    "offsides",
    "cards",
)
ODDS_KEYWORDS = (
    "shot",
    "corner",
    "card",
    "foul",
    "offside",
    "goal",
    "handicap",
    "team total",
    "total",
    "head",
    "h2h",
)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_date(value: str) -> date:
    return parse_dt(value).astimezone(ZoneInfo(TZ_NAME)).date()


def cached(
    client: APIFootballClient,
    kind: str,
    key: str,
    endpoint: str,
    **params: Any,
) -> list[dict[str, Any]]:
    hit = load_json(kind, key)
    if hit is not None:
        return hit
    rows = client.get(endpoint, **params).response
    save_json(kind, key, rows)
    return rows


def discover_ligamx(client: APIFootballClient, season: int) -> dict[str, Any]:
    # API-Football does not allow `search` to be combined with `country`
    # or `season`. Query the Mexico+season catalog first, then rank locally.
    rows = client.leagues(country="Mexico", season=season).response

    # Fallbacks are intentionally separate calls because the API rejects
    # search+country/season combinations.
    if not rows:
        rows = client.leagues(search="Liga MX").response
    if not rows:
        rows = client.leagues(country="Mexico").response
    if not rows:
        raise SystemExit(f"No Mexico league rows returned for season {season}.")

    def score(row: dict[str, Any]) -> tuple[int, int]:
        league = row.get("league", {})
        name = str(league.get("name") or "").strip().lower()
        league_type = str(league.get("type") or "").lower()
        s = 0
        if name == "liga mx":
            s += 1000
        elif "liga mx" in name:
            s += 500
        if league_type == "league":
            s += 100
        if any(x in name for x in ("femenil", "u20", "u23", "expansion")):
            s -= 500
        return s, -int(league.get("id") or 0)

    best = max(rows, key=score)
    league = best.get("league", {})
    if score(best)[0] < 100:
        print("WARNING: exact Liga MX row was not obvious. Candidates:")
        for row in sorted(rows, key=score, reverse=True)[:10]:
            lg = row.get("league", {})
            print(f"  {lg.get('id')} | {lg.get('name')} | {lg.get('type')}")

    return {
        "id": int(league["id"]),
        "name": str(league.get("name") or "Liga MX"),
        "type": str(league.get("type") or ""),
        "country": str(best.get("country", {}).get("name") or "Mexico"),
    }


def fixture_list_for_team(
    client: APIFootballClient,
    team_id: int,
    league_id: int,
    seasons: list[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for season in seasons:
        key = f"ligamx_team_{team_id}_league_{league_id}_season_{season}"
        rows.extend(
            cached(
                client,
                "ligamx_fixture_lists",
                key,
                "fixtures",
                team=team_id,
                league=league_id,
                season=season,
                timezone=TZ_NAME,
            )
        )
    dedup: dict[int, dict[str, Any]] = {}
    for row in rows:
        fid = row.get("fixture", {}).get("id")
        if fid is not None:
            dedup[int(fid)] = row
    return list(dedup.values())


def fixture_stats(client: APIFootballClient, fixture_id: int) -> list[dict[str, Any]]:
    return cached(
        client,
        "fixture_stats",
        f"fixture_{fixture_id}",
        "fixtures/statistics",
        fixture=fixture_id,
    )


def perspective(
    row: dict[str, Any],
    team_id: int,
    parsed: dict[int, dict[str, float | None]],
) -> dict[str, Any]:
    home = row["teams"]["home"]
    away = row["teams"]["away"]
    is_home = int(home["id"]) == team_id
    own = home if is_home else away
    opp = away if is_home else home
    own_stats = parsed.get(team_id, {})
    opp_stats = parsed.get(int(opp["id"]), {})
    goals = row.get("goals", {})

    return {
        "fixture_id": int(row["fixture"]["id"]),
        "date": row["fixture"]["date"],
        "round": row.get("league", {}).get("round"),
        "venue": "home" if is_home else "away",
        "opponent_id": int(opp["id"]),
        "opponent_name": str(opp.get("name") or ""),
        "goals_for": goals.get("home") if is_home else goals.get("away"),
        "goals_against": goals.get("away") if is_home else goals.get("home"),
        "stats_for": {s: own_stats.get(s) for s in MODEL_STATS},
        "stats_against": {s: opp_stats.get(s) for s in MODEL_STATS},
    }


def mean_non_null(values: list[float | int | None]) -> float | None:
    good = [float(x) for x in values if x is not None]
    return statistics.fmean(good) if good else None


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_matches": len(rows), "stats": {}}
    for stat in ("goals",) + MODEL_STATS:
        if stat == "goals":
            f = [r.get("goals_for") for r in rows]
            a = [r.get("goals_against") for r in rows]
        else:
            f = [r.get("stats_for", {}).get(stat) for r in rows]
            a = [r.get("stats_against", {}).get(stat) for r in rows]
        out["stats"][stat] = {
            "for": mean_non_null(f),
            "against": mean_non_null(a),
            "n_for": sum(x is not None for x in f),
            "n_against": sum(x is not None for x in a),
        }
    return out


def build_team_profile(
    client: APIFootballClient,
    team_id: int,
    league_id: int,
    seasons: list[int],
    target: date,
    matches: int,
) -> dict[str, Any]:
    rows = fixture_list_for_team(client, team_id, league_id, seasons)
    eligible = [
        row
        for row in rows
        if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
        and local_date(row["fixture"]["date"]) < target
    ]
    eligible.sort(key=lambda x: parse_dt(x["fixture"]["date"]), reverse=True)
    eligible = eligible[:matches]
    eligible.sort(key=lambda x: parse_dt(x["fixture"]["date"]))

    history: list[dict[str, Any]] = []
    for idx, row in enumerate(eligible, start=1):
        fid = int(row["fixture"]["id"])
        parsed = parse_fixture_statistics(fixture_stats(client, fid))
        history.append(perspective(row, team_id, parsed))
        if idx % 10 == 0 or idx == len(eligible):
            print(f"      history stats {idx}/{len(eligible)}")

    return {
        "team_id": team_id,
        "history": history,
        "overall": summarize_rows(history),
        "home": summarize_rows([r for r in history if r["venue"] == "home"]),
        "away": summarize_rows([r for r in history if r["venue"] == "away"]),
    }


def build_league_baseline(
    client: APIFootballClient,
    league_id: int,
    seasons: list[int],
    target: date,
    window: int,
) -> dict[str, Any]:
    fixtures: list[dict[str, Any]] = []
    for season in seasons:
        key = f"ligamx_league_{league_id}_season_{season}"
        fixtures.extend(
            cached(
                client,
                "ligamx_fixture_lists",
                key,
                "fixtures",
                league=league_id,
                season=season,
                timezone=TZ_NAME,
            )
        )

    dedup = {
        int(row["fixture"]["id"]): row
        for row in fixtures
        if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
        and local_date(row["fixture"]["date"]) < target
    }
    ordered = sorted(dedup.values(), key=lambda x: parse_dt(x["fixture"]["date"]))
    if window > 0:
        ordered = ordered[-window:]

    values = {
        s: {"home": [], "away": []}
        for s in ("goals",) + MODEL_STATS
    }

    for idx, row in enumerate(ordered, start=1):
        home_id = int(row["teams"]["home"]["id"])
        away_id = int(row["teams"]["away"]["id"])
        parsed = parse_fixture_statistics(fixture_stats(client, int(row["fixture"]["id"])))
        h = parsed.get(home_id, {})
        a = parsed.get(away_id, {})
        values["goals"]["home"].append(row.get("goals", {}).get("home"))
        values["goals"]["away"].append(row.get("goals", {}).get("away"))
        for stat in MODEL_STATS:
            values[stat]["home"].append(h.get(stat))
            values[stat]["away"].append(a.get(stat))
        if idx % 25 == 0 or idx == len(ordered):
            print(f"    league baseline stats {idx}/{len(ordered)}")

    summary: dict[str, Any] = {
        "n_fixtures": len(ordered),
        "window": window,
        "stats": {},
    }
    for stat, sides in values.items():
        home_good = [float(x) for x in sides["home"] if x is not None]
        away_good = [float(x) for x in sides["away"] if x is not None]
        combined = home_good + away_good
        fit = fit_count_distribution(combined)
        summary["stats"][stat] = {
            "home_mean": statistics.fmean(home_good) if home_good else None,
            "away_mean": statistics.fmean(away_good) if away_good else None,
            "n_home": len(home_good),
            "n_away": len(away_good),
            "dispersion_r": fit.r,
            "distribution": fit.kind,
        }
    return summary


def relevant_odds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    markets: dict[tuple[Any, str], dict[str, Any]] = {}
    for row in rows:
        for bookmaker in row.get("bookmakers", []):
            book = str(bookmaker.get("name") or bookmaker.get("id") or "Unknown")
            for bet in bookmaker.get("bets", []):
                name = str(bet.get("name") or "")
                if not any(k in name.lower() for k in ODDS_KEYWORDS):
                    continue
                key = (bet.get("id"), name)
                e = markets.setdefault(
                    key,
                    {
                        "bet_id": bet.get("id"),
                        "name": name,
                        "bookmakers": set(),
                        "quotes": [],
                    },
                )
                e["bookmakers"].add(book)
                for value in bet.get("values", []):
                    e["quotes"].append(
                        {
                            "bookmaker": book,
                            "value": value.get("value"),
                            "odd": value.get("odd"),
                        }
                    )
    serial = []
    for e in markets.values():
        serial.append(
            {
                "bet_id": e["bet_id"],
                "name": e["name"],
                "bookmakers": sorted(e["bookmakers"]),
                "book_count": len(e["bookmakers"]),
                "quotes": e["quotes"],
            }
        )
    serial.sort(key=lambda x: (str(x["name"]).lower(), str(x["bet_id"])))
    return {"market_count": len(serial), "markets": serial}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect an API-Football-only Liga MX slate for tonight: fixtures, "
            "recent team stat histories, league baselines, standings, injuries, "
            "lineups, H2H and sportsbook stat markets."
        )
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--matches", type=int, default=30)
    parser.add_argument("--league-window", type=int, default=120)
    parser.add_argument(
        "--history-seasons",
        type=int,
        nargs="+",
        default=None,
        help="Season start years to search for history. Defaults to season, season-1, season-2.",
    )
    args = parser.parse_args()

    target = date.fromisoformat(args.date)
    seasons = args.history_seasons or [args.season, args.season - 1, args.season - 2]
    client = APIFootballClient()

    league = discover_ligamx(client, args.season)
    league_id = int(league["id"])
    print(f"LIGA MX API-FOOTBALL COLLECTOR — {args.date}")
    print(f"League: {league['name']} | id={league_id} | season={args.season}")
    print(f"Timezone: {TZ_NAME}\n")

    slate_key = f"ligamx_{args.date}_season_{args.season}"
    fixtures = cached(
        client,
        "ligamx_slates",
        slate_key,
        "fixtures",
        league=league_id,
        season=args.season,
        date=args.date,
        timezone=TZ_NAME,
    )
    if not fixtures:
        raise SystemExit(
            f"No Liga MX fixtures returned for {args.date}. "
            "If the API season label differs, rerun with --season YEAR."
        )

    print(f"Tonight: {len(fixtures)} match(es)")
    for row in fixtures:
        f = row["fixture"]
        print(
            f"  {f['id']} | {row['teams']['home']['name']} vs "
            f"{row['teams']['away']['name']} | {f['date']}"
        )

    print("\nBuilding league environment...")
    baseline = build_league_baseline(
        client, league_id, seasons, target, args.league_window
    )

    standings = cached(
        client,
        "ligamx_standings",
        f"league_{league_id}_season_{args.season}",
        "standings",
        league=league_id,
        season=args.season,
    )

    payload: dict[str, Any] = {
        "meta": {
            "source": "API-Football only",
            "date": args.date,
            "season": args.season,
            "timezone": TZ_NAME,
            "recent_matches_per_team": args.matches,
            "history_seasons": seasons,
            "league_window": args.league_window,
            "null_policy": "missing API stats remain null; never imputed as zero",
        },
        "league": league,
        "standings": standings,
        "league_baseline": baseline,
        "fixtures": {},
    }

    for row in fixtures:
        fixture = row["fixture"]
        fixture_id = int(fixture["id"])
        home = row["teams"]["home"]
        away = row["teams"]["away"]
        home_id = int(home["id"])
        away_id = int(away["id"])

        print("\n" + "=" * 96)
        print(f"{home['name']} vs {away['name']} | fixture {fixture_id}")

        print(f"  {home['name']}: collecting last {args.matches} league matches")
        home_profile = build_team_profile(
            client, home_id, league_id, seasons, target, args.matches
        )
        print(f"  {away['name']}: collecting last {args.matches} league matches")
        away_profile = build_team_profile(
            client, away_id, league_id, seasons, target, args.matches
        )

        injuries = cached(
            client,
            "ligamx_injuries",
            f"fixture_{fixture_id}",
            "injuries",
            fixture=fixture_id,
        )
        lineups = cached(
            client,
            "ligamx_lineups",
            f"fixture_{fixture_id}",
            "fixtures/lineups",
            fixture=fixture_id,
        )
        h2h = cached(
            client,
            "ligamx_h2h",
            f"{home_id}_{away_id}_last10",
            "fixtures",
            h2h=f"{home_id}-{away_id}",
            last=10,
            timezone=TZ_NAME,
        )
        raw_odds = cached(
            client,
            "odds",
            f"fixture_{fixture_id}",
            "odds",
            fixture=fixture_id,
        )
        odds = relevant_odds(raw_odds)

        payload["fixtures"][str(fixture_id)] = {
            "fixture": row,
            "home_profile": home_profile,
            "away_profile": away_profile,
            "injuries": injuries,
            "lineups": lineups,
            "h2h": h2h,
            "odds": odds,
        }

        def cov(profile: dict[str, Any], stat: str) -> str:
            s = profile["overall"]["stats"][stat]
            return f"{s['n_for']}/{profile['overall']['n_matches']}"

        print(
            "  coverage "
            f"shots {cov(home_profile,'shots')} / {cov(away_profile,'shots')} | "
            f"SOT {cov(home_profile,'shots_on_target')} / {cov(away_profile,'shots_on_target')} | "
            f"corners {cov(home_profile,'corners')} / {cov(away_profile,'corners')} | "
            f"fouls {cov(home_profile,'fouls')} / {cov(away_profile,'fouls')} | "
            f"offsides {cov(home_profile,'offsides')} / {cov(away_profile,'offsides')}"
        )
        print(
            f"  injuries={len(injuries)} | lineups={len(lineups)} | "
            f"h2h={len(h2h)} | relevant odds markets={odds['market_count']}"
        )

    path = save_json(
        "ligamx_tonight",
        args.date.replace("-", "_"),
        payload,
    )
    print("\n" + "=" * 96)
    print(f"Saved model-ready Liga MX slate to {path}")
    print("Source policy: API-Football only. No web data mixed in.")
    print("Next step: build the Liga MX Edge projections and fair stat markets from this file.")


if __name__ == "__main__":
    main()

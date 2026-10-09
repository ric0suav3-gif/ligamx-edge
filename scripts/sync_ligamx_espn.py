"""Build the no-key Liga MX model snapshot from ESPN's public match feed.

The checked-in v30 base is immutable. Every run replays completed matches from
that base, so re-running the collector cannot double-count a fixture.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "data" / "ligamx_base_v30.json"
SNAPSHOT_PATH = ROOT / "data" / "ligamx_espn_latest.json"
TZ = ZoneInfo("America/Mexico_City")
ALPHAS = {"Goals": 0.15, "Shots": 0.15, "Shots on Target": 0.15, "Corners": 0.15, "Fouls": 0.15, "Offsides": 0.0539, "Yellow": 0.0539, "Red": 0.0539, "Cards": 0.0539}
STATS = {
    "Shots": "totalShots",
    "Shots on Target": "shotsOnTarget",
    "Corners": "wonCorners",
    "Fouls": "foulsCommitted",
    "Yellow": "yellowCards",
    "Red": "redCards",
    "Offsides": "offsides",
}
ALIASES = {
    "santos laguna": "Santos",
    "pumas unam": "Pumas UNAM",
    "tigres uanl": "Tigres UANL",
    "fc juarez": "FC Juarez",
    "atletico de san luis": "Atlético de San Luis",
    "leon": "León",
    "america": "América",
    "queretaro": "Querétaro",
    "tijuana": "Tijuana",
}
PICKS = [
    ("p01", "2026-09-12", "Toluca", "Atlas", "away", "Shots", "under", 10.5, "Atlas U10.5 shots"),
    ("p02", "2026-09-12", "Toluca", "Atlas", "home", "Shots on Target", "over", 4.5, "Toluca O4.5 SOT"),
    ("p03", "2026-09-12", "Toluca", "Atlas", "total", "Fouls", "over", 24.5, "Toluca–Atlas O24.5 fouls"),
    ("p04", "2026-09-12", "Toluca", "Atlas", "away", "Corners", "under", 3.5, "Atlas U3.5 corners"),
    ("p05", "2026-09-12", "Monterrey", "Tigres UANL", "home", "Shots on Target", "over", 5.5, "Monterrey O5.5 SOT"),
    ("p06", "2026-09-12", "Monterrey", "Tigres UANL", "away", "Shots", "under", 14.5, "Tigres U14.5 shots"),
    ("p07", "2026-09-12", "Monterrey", "Tigres UANL", "away", "Goals", "under", 1.5, "Tigres U1.5 goals"),
    ("p08", "2026-09-12", "Monterrey", "Tigres UANL", "total", "Offsides", "under", 3.5, "Monterrey–Tigres U3.5 offsides"),
    ("p09", "2026-09-12", "Cruz Azul", "América", "total", "Fouls", "over", 23.5, "Cruz Azul–América O23.5 fouls"),
    ("p10", "2026-09-12", "Cruz Azul", "América", "total", "Offsides", "under", 4.5, "Cruz Azul–América U4.5 offsides"),
    ("p11", "2026-09-12", "Cruz Azul", "América", "away", "Shots", "under", 12.5, "América U12.5 shots"),
    ("p12", "2026-09-12", "Cruz Azul", "América", "total", "Corners", "over", 8.5, "Cruz Azul–América O8.5 corners"),
    ("p13", "2026-09-13", "Guadalajara", "Pumas UNAM", "away", "Corners", "under", 3.5, "Pumas U3.5 corners"),
]


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ligamx-edge/32"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def name(raw: str, teams: dict) -> str | None:
    import unicodedata

    key = "".join(c for c in unicodedata.normalize("NFD", raw.lower()) if not unicodedata.combining(c))
    return ALIASES.get(key) or next((t for t in teams if t == raw or t.lower() == raw.lower()), None)


def local_date(event: dict) -> str:
    return datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(TZ).date().isoformat()


def match_data(event: dict, teams: dict) -> dict | None:
    summary = fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/summary?event={event['id']}")
    comp = event["competitions"][0]
    sides = {}
    for side in comp["competitors"]:
        team = name(side["team"]["displayName"], teams)
        if not team:
            return None
        sides[side["homeAway"]] = {"name": team, "Goals": int(side["score"])}
    for side in summary.get("boxscore", {}).get("teams", []):
        team = name(side["team"]["displayName"], teams)
        if not team:
            continue
        target = sides["home"] if sides["home"]["name"] == team else sides["away"]
        sm = {x["name"]: x["displayValue"] for x in side.get("statistics", [])}
        for stat, key in STATS.items():
            try:
                target[stat] = int(sm[key])
            except (KeyError, TypeError, ValueError):
                target[stat] = None
        target["Cards"] = None if target["Yellow"] is None or target["Red"] is None else target["Yellow"] + target["Red"]
    return {"id": event["id"], "date": local_date(event), "kickoff": event["date"], "home": sides["home"], "away": sides["away"]}


def load_base() -> dict:
    if BASE_PATH.exists():
        return json.loads(BASE_PATH.read_text(encoding="utf-8"))
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    match = re.search(r"^const MODELS = (.+);$", html, re.MULTILINE)
    if not match:
        raise RuntimeError("Embedded MODELS JSON not found")
    base = json.loads(match.group(1))["ligamx"]
    BASE_PATH.parent.mkdir(exist_ok=True)
    BASE_PATH.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return base


def grade(matches: list[dict]) -> list[dict]:
    lookup = {(x["date"], x["home"]["name"], x["away"]["name"]): x for x in matches}
    out = []
    for pid, day, home, away, scope, stat, direction, line, label in PICKS:
        match = lookup.get((day, home, away))
        actual = None
        if match:
            if scope == "total":
                h, a = match["home"].get(stat), match["away"].get(stat)
                actual = h + a if h is not None and a is not None else None
            else:
                actual = match[scope].get(stat)
        result = "na" if actual is None else "win" if ((actual > line) if direction == "over" else (actual < line)) else "loss"
        out.append({"id": pid, "date": day, "label": label, "actual": actual, "result": result, "sourceEventId": match["id"] if match else None})
    return out


def update_model(base: dict, matches: list[dict], today: str, grades: list[dict]) -> dict:
    from copy import deepcopy

    model = deepcopy(base)
    cutoff = base["meta"]["date_range"][1]
    added = 0
    for match in matches:
        if not (cutoff < match["date"] < today):
            continue
        home, away = match["home"], match["away"]
        hsplit = model["teams"][home["name"]]["home"]
        asplit = model["teams"][away["name"]]["away"]
        for stat in model["meta"]["stats"]:
            hv, av = home.get(stat), away.get(stat)
            if hv is None or av is None or stat not in hsplit or stat not in asplit:
                continue
            alpha = ALPHAS[stat]
            for split, own, opp in ((hsplit, hv, av), (asplit, av, hv)):
                split[stat]["for"] = (1 - alpha) * split[stat]["for"] + alpha * own
                split[stat]["against"] = (1 - alpha) * split[stat]["against"] + alpha * opp
        hsplit["n"] += 1
        asplit["n"] += 1
        added += 1
    meta = model["meta"]
    meta.update({
        "version": "v32-espn", "built": today, "ui_build": today,
        "matches": base["meta"]["matches"] + added,
        "date_range": [base["meta"]["date_range"][0], max((x["date"] for x in matches if x["date"] < today), default=cutoff)],
        "fixture_source": "ESPN public scoreboard", "stat_source": "ESPN match box scores",
        "api_refresh_status": f"{added} completed matches replayed from v30 base without API key",
        "grade_count": sum(x["result"] != "na" for x in grades),
        "referee_weight": 0.5,
        "incremental_alpha": ALPHAS,
        "data_scope": "Apertura 2026 through " + max((x["date"] for x in matches if x["date"] < today), default=cutoff),
    })
    return model


def standings_data(teams: dict) -> dict:
    raw = fetch("https://site.api.espn.com/apis/v2/sports/soccer/mex.1/standings?season=2026")
    group = next(g for g in raw["children"] if "Apertura" in g["name"])
    out = {}
    for entry in group["standings"]["entries"]:
        team = name(entry["team"]["displayName"], teams)
        if not team:
            continue
        stats = {s["name"]: s.get("value") for s in entry["stats"]}
        out[team] = [int(stats[k]) for k in ("points", "gamesPlayed", "pointsFor", "pointsAgainst")]
    return out


def replace_embedded(model: dict, standings: dict) -> None:
    for path in (ROOT / "index.html", ROOT / "ligamx edge.html"):
        content = path.read_text(encoding="utf-8")
        match = re.search(r"^const MODELS = (.+);$", content, re.MULTILINE)
        if not match:
            raise RuntimeError(f"Embedded MODELS JSON not found in {path}")
        all_models = json.loads(match.group(1))
        all_models["ligamx"] = model
        content = content[:match.start(1)] + json.dumps(all_models, ensure_ascii=False, separators=(",", ":")) + content[match.end(1):]
        stand_match = re.search(r"^const LIGAMX_STANDINGS = (.+);$", content, re.MULTILINE)
        if not stand_match:
            raise RuntimeError(f"Embedded standings not found in {path}")
        content = content[:stand_match.start(1)] + json.dumps(standings, ensure_ascii=False, separators=(",", ":")) + content[stand_match.end(1):]
        path.write_text(content, encoding="utf-8")


def main() -> None:
    base = load_base()
    today = datetime.now(TZ).date().isoformat()
    board = fetch("https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard?dates=2026&limit=500")
    cutoff = base["meta"]["date_range"][1]
    events = [e for e in board["events"] if e["status"]["type"]["completed"] and cutoff < local_date(e) < today]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        matches = [x for x in pool.map(lambda e: match_data(e, base["teams"]), events) if x]
    matches.sort(key=lambda x: (x["kickoff"], x["id"]))
    grades = grade(matches)
    model = update_model(base, matches, today, grades)
    standings = standings_data(base["teams"])
    SNAPSHOT_PATH.write_text(json.dumps({"source": "ESPN", "generatedAt": datetime.now(timezone.utc).isoformat(), "todayMexico": today, "matches": matches, "grades": grades, "standings": standings}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_embedded(model, standings)
    print(f"Updated {len(matches)} completed Liga MX matches through {model['meta']['date_range'][1]}")
    print(f"Saved September picks: {sum(x['result']=='win' for x in grades)}W-{sum(x['result']=='loss' for x in grades)}L-{sum(x['result']=='na' for x in grades)}NA")
    for x in grades:
        print(f"{x['id']} {x['result']:4} actual={x['actual']!s:>3} {x['label']}")


if __name__ == "__main__":
    main()

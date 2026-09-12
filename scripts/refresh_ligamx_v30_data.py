from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.api_football import APIFootballClient
from ingest.cache import load_json, save_json
from ingest.statistics import parse_fixture_statistics

TZ = "America/Mexico_City"
LEAGUE_ID = 262
COMPLETED = {"FT", "AET", "PEN"}
ALPHA = 0.0539
MARKER = "const MODELS = "

STAT_MAP = {
    "Shots": "shots",
    "Shots on Target": "shots_on_target",
    "Corners": "corners",
    "Fouls": "fouls",
    "Yellow": "yellow",
    "Red": "red",
    "Offsides": "offsides",
    "Cards": "cards",
}

ALIASES = {
    "Club America": "América",
    "America": "América",
    "Atletico San Luis": "Atlético de San Luis",
    "Atletico de San Luis": "Atlético de San Luis",
    "Guadalajara Chivas": "Guadalajara",
    "Santos Laguna": "Santos",
    "U.N.A.M. - Pumas": "Pumas UNAM",
    "UNAM Pumas": "Pumas UNAM",
    "Juarez": "FC Juarez",
    "Queretaro": "Querétaro",
}


def parse_dt(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def local_day(v: str) -> date:
    return parse_dt(v).astimezone(ZoneInfo(TZ)).date()


def clean_ref(v: Any) -> str | None:
    if not v:
        return None
    return re.sub(r",\s*Mexico$", "", str(v).strip(), flags=re.I).strip() or None


def cached(client: APIFootballClient, kind: str, key: str, endpoint: str, **params: Any):
    hit = load_json(kind, key)
    if hit is not None:
        return hit
    rows = client.get(endpoint, **params).response
    save_json(kind, key, rows)
    return rows


def stats(client: APIFootballClient, fid: int):
    rows = cached(client, "fixture_stats", f"fixture_{fid}", "fixtures/statistics", fixture=fid)
    return parse_fixture_statistics(rows)


def extract_models(html: str):
    i = html.find(MARKER)
    if i < 0:
        raise RuntimeError("MODELS object not found")
    start = i + len(MARKER)
    while html[start].isspace():
        start += 1
    models, used = json.JSONDecoder().raw_decode(html[start:])
    return models, start, start + used


def norm(s: str) -> str:
    import unicodedata
    x = unicodedata.normalize("NFD", s)
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", x.lower())


def team_name(api_name: str, teams: dict[str, Any]) -> str | None:
    if api_name in teams:
        return api_name
    mapped = ALIASES.get(api_name)
    if mapped in teams:
        return mapped
    n = norm(api_name)
    exact = [t for t in teams if norm(t) == n]
    if exact:
        return exact[0]
    partial = [t for t in teams if n in norm(t) or norm(t) in n]
    return partial[0] if len(partial) == 1 else None


def upd(old: Any, value: Any):
    if value is None:
        return old
    if old is None:
        return float(value)
    return (1 - ALPHA) * float(old) + ALPHA * float(value)


def update_team(team: dict[str, Any], split: str, own: dict[str, Any], opp: dict[str, Any], gf: Any, ga: Any):
    row = team[split]
    for model_stat, api_stat in STAT_MAP.items():
        row[model_stat]["for"] = upd(row[model_stat].get("for"), own.get(api_stat))
        row[model_stat]["against"] = upd(row[model_stat].get("against"), opp.get(api_stat))
    row["Goals"]["for"] = upd(row["Goals"].get("for"), gf)
    row["Goals"]["against"] = upd(row["Goals"].get("against"), ga)
    row["n"] = int(row.get("n") or 0) + 1


def completed_after(client: APIFootballClient, season: int, start: date, end: date):
    if end < start:
        return []
    rows = cached(
        client,
        "ligamx_v30_incremental",
        f"{season}_{start}_{end}",
        "fixtures",
        league=LEAGUE_ID,
        season=season,
        **{"from": start.isoformat(), "to": end.isoformat()},
        timezone=TZ,
    )
    return [x for x in rows if x.get("fixture", {}).get("status", {}).get("short") in COMPLETED]


def referee_rows(client: APIFootballClient, seasons: list[int], cutoff: date):
    out: dict[int, dict[str, Any]] = {}
    for season in seasons:
        rows = cached(
            client,
            "ligamx_ref_lists",
            f"season_{season}",
            "fixtures",
            league=LEAGUE_ID,
            season=season,
            timezone=TZ,
        )
        for x in rows:
            fx = x.get("fixture", {})
            if (
                fx.get("status", {}).get("short") in COMPLETED
                and local_day(fx["date"]) < cutoff
                and clean_ref(fx.get("referee"))
            ):
                out[int(fx["id"])] = x
    return sorted(out.values(), key=lambda x: parse_dt(x["fixture"]["date"]))


def build_refs(client: APIFootballClient, seasons: list[int], cutoff: date, existing: dict[str, Any]):
    agg = defaultdict(lambda: {"n": 0, "f_sum": 0.0, "f_n": 0, "y_sum": 0.0, "y_n": 0})
    all_f, all_y = [], []
    rows = referee_rows(client, seasons, cutoff)
    for i, x in enumerate(rows, 1):
        ref = clean_ref(x["fixture"].get("referee"))
        if not ref:
            continue
        p = stats(client, int(x["fixture"]["id"]))
        hid = int(x["teams"]["home"]["id"])
        aid = int(x["teams"]["away"]["id"])
        h, a = p.get(hid, {}), p.get(aid, {})
        r = agg[ref]
        r["n"] += 1
        if h.get("fouls") is not None and a.get("fouls") is not None:
            v = float(h["fouls"]) + float(a["fouls"])
            r["f_sum"] += v
            r["f_n"] += 1
            all_f.append(v)
        if h.get("yellow") is not None and a.get("yellow") is not None:
            v = float(h["yellow"]) + float(a["yellow"])
            r["y_sum"] += v
            r["y_n"] += 1
            all_y.append(v)
        if i % 25 == 0 or i == len(rows):
            print(f"  referee stats {i}/{len(rows)}")

    lg_f = sum(all_f) / len(all_f) if all_f else None
    lg_y = sum(all_y) / len(all_y) if all_y else None
    result = {}
    for name in sorted(set(existing) | set(agg)):
        old = existing.get(name, {})
        r = agg.get(name)
        if r:
            af = r["f_sum"] / r["f_n"] if r["f_n"] else None
            ay = r["y_sum"] / r["y_n"] if r["y_n"] else None
            raw = af / lg_f if af is not None and lg_f else float(old.get("mult") or 1.0)
            w = r["f_n"] / (r["f_n"] + 10.0) if r["f_n"] else 0.0
            mult = 1.0 + w * (raw - 1.0)
            result[name] = {
                "mult": round(mult, 4),
                "avg_fouls": None if af is None else round(af, 2),
                "avg_yellow": None if ay is None else round(ay, 2),
                "n": int(r["n"]),
                "n_fouls": int(r["f_n"]),
                "n_yellow": int(r["y_n"]),
                "source": "API-Football",
                "historical_n_v29": old.get("n"),
                "historical_mult_v29": old.get("mult"),
            }
        else:
            result[name] = {
                "mult": float(old.get("mult") or 1.0),
                "avg_fouls": None,
                "avg_yellow": None,
                "n": int(old.get("n") or 0),
                "n_fouls": 0,
                "n_yellow": 0,
                "source": "V29 fallback",
                "historical_n_v29": old.get("n"),
                "historical_mult_v29": old.get("mult"),
            }
    return result, {
        "seasons": seasons,
        "cutoff": cutoff.isoformat(),
        "fixtures": len(rows),
        "league_avg_fouls": None if lg_f is None else round(lg_f, 2),
        "league_avg_yellow": None if lg_y is None else round(lg_y, 2),
        "referee_count": len(result),
    }


def patch_ref_ui(html: str) -> str:
    old = """    rs.innerHTML='<option value="">Árbitro: promedio de liga</option>'+
      refs.map(([n,d])=>`<option value="${n}">${n} · ${d.mult>1?'+':''}${((d.mult-1)*100).toFixed(0)}% faltas</option>`).join('');
    rw.style.display='block';"""
    new = """    rs.innerHTML='<option value="">Árbitro: promedio de liga</option>'+
      refs.map(([n,d])=>{
        const y=d.avg_yellow==null?'—':Number(d.avg_yellow).toFixed(1);
        const f=d.avg_fouls==null?'—':Number(d.avg_fouls).toFixed(1);
        return `<option value="${n}">${n} · ${y} amarillas · ${f} faltas · n=${d.n||0}</option>`;
      }).join('');
    rw.style.display='block';"""
    if old in html:
        html = html.replace(old, new, 1)
    elif "d.avg_yellow==null" not in html or "d.avg_fouls==null" not in html:
        raise RuntimeError("Referee dropdown renderer not found")

    html = html.replace(
        "Tarjetas: no hay efecto de árbitro comprobable (es ruido) — se quedan cerca del promedio de liga.<br>Faltas: el árbitro SÍ importa; elígelo arriba para ajustar.",
        "Árbitros: el selector muestra promedio de amarillas y faltas de API-Football con tamaño de muestra.<br>Faltas: el árbitro ajusta el modelo; amarillas se muestran pero no ajustan hasta validar ese efecto.",
        1,
    )
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--ref-seasons", type=int, nargs="+", default=[2026, 2025])
    ap.add_argument("--base-html", default="exports/LigaMX_Edge_V30.html")
    args = ap.parse_args()

    target = date.fromisoformat(args.date)
    base_html = ROOT / args.base_html
    prior_html = ROOT / "archive" / "ligamx_edge_v29_full.html"
    if not base_html.exists() or not prior_html.exists():
        raise SystemExit("Missing V30 UI base or preserved V29 archive.")

    client = APIFootballClient()

    prior_text = prior_html.read_text(encoding="utf-8")
    prior_models, _, _ = extract_models(prior_text)
    liga = prior_models["ligamx"]
    meta = liga["meta"]
    base_count = int(meta["matches"])
    prior_end = date.fromisoformat(meta["date_range"][1])

    fresh = completed_after(client, args.season, prior_end + timedelta(days=1), target - timedelta(days=1))
    fresh.sort(key=lambda x: parse_dt(x["fixture"]["date"]))
    print(f"Fresh completed Liga MX matches after V29 cutoff: {len(fresh)}")

    skipped = set()
    for i, x in enumerate(fresh, 1):
        fid = int(x["fixture"]["id"])
        hid = int(x["teams"]["home"]["id"])
        aid = int(x["teams"]["away"]["id"])
        hp, apn = x["teams"]["home"]["name"], x["teams"]["away"]["name"]
        hm = team_name(hp, liga["teams"])
        am = team_name(apn, liga["teams"])
        p = stats(client, fid)
        hs, as_ = p.get(hid, {}), p.get(aid, {})
        if hm:
            update_team(liga["teams"][hm], "home", hs, as_, x.get("goals", {}).get("home"), x.get("goals", {}).get("away"))
        else:
            skipped.add(hp)
        if am:
            update_team(liga["teams"][am], "away", as_, hs, x.get("goals", {}).get("away"), x.get("goals", {}).get("home"))
        else:
            skipped.add(apn)
        print(f"  merged {i}/{len(fresh)} | {hp} vs {apn}")

    meta["base_version"] = "v29"
    meta["version"] = "v30"
    meta["built"] = target.isoformat()
    meta["matches"] = base_count + len(fresh)
    meta["fresh_matches_added"] = len(fresh)
    meta["fixture_source"] = "API-Football"
    meta["api_incremental_from"] = (prior_end + timedelta(days=1)).isoformat()
    meta["api_incremental_through"] = (target - timedelta(days=1)).isoformat()
    meta["incremental_alpha_split"] = ALPHA
    if fresh:
        meta["date_range"][1] = max(local_day(x["fixture"]["date"]) for x in fresh).isoformat()

    print("Building referee table from API-Football...")
    refs, ref_meta = build_refs(client, sorted(set(args.ref_seasons), reverse=True), target, liga.get("referees", {}))
    liga["referees"] = refs
    meta["referee_api"] = ref_meta

    ui = base_html.read_text(encoding="utf-8")
    _, start, end = extract_models(ui)
    ui = ui[:start] + json.dumps(prior_models, ensure_ascii=False, separators=(",", ":")) + ui[end:]
    ui = patch_ref_ui(ui)
    base_html.write_text(ui, encoding="utf-8")

    ref_out = ROOT / "exports" / f"ligamx_referees_{target.isoformat().replace('-', '_')}.json"
    ref_out.write_text(json.dumps({"meta": ref_meta, "referees": refs}, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(f"V30 matches: {meta['matches']} = {base_count} + {len(fresh)} new completed fixtures")
    print(f"Data through: {meta['date_range'][1]}")
    print(f"Referees available: {len(refs)}")
    print(f"League ref sample: {ref_meta['league_avg_yellow']} yellows | {ref_meta['league_avg_fouls']} fouls")
    if skipped:
        print(f"WARNING unmapped teams: {sorted(skipped)}")
    print(f"Updated HTML: {base_html}")
    print(f"Referee export: {ref_out}")
    print("Referee yellow averages are display-only; foul multiplier remains the modeled referee adjustment.")


if __name__ == "__main__":
    main()

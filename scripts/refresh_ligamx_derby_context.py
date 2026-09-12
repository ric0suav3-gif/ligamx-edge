from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import unicodedata
from datetime import date, datetime, timezone
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
MARKER = "const MODELS = "
COMPLETED = {"FT", "AET", "PEN"}

DERBIES = {
    frozenset(("Monterrey", "Tigres UANL")): {"name": "Clásico Regio", "slug": "clasico-regio"},
    frozenset(("Cruz Azul", "Club America")): {"name": "Clásico Joven", "slug": "clasico-joven"},
}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_day(value: str) -> date:
    return parse_dt(value).astimezone(ZoneInfo(TZ)).date()


def norm(value: str) -> str:
    x = unicodedata.normalize("NFD", str(value or ""))
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


def extract_models(html: str) -> tuple[dict[str, Any], int, int]:
    i = html.find(MARKER)
    if i < 0:
        raise RuntimeError("MODELS object not found")
    start = i + len(MARKER)
    while start < len(html) and html[start].isspace():
        start += 1
    models, used = json.JSONDecoder().raw_decode(html[start:])
    return models, start, start + used


def cached(client: APIFootballClient, kind: str, key: str, endpoint: str, **params: Any):
    hit = load_json(kind, key)
    if hit is not None:
        return hit
    rows = client.get(endpoint, **params).response
    save_json(kind, key, rows)
    return rows


def fixture_stats(client: APIFootballClient, fixture_id: int):
    rows = cached(
        client,
        "fixture_stats",
        f"fixture_{fixture_id}",
        "fixtures/statistics",
        fixture=fixture_id,
    )
    return parse_fixture_statistics(rows)


def clean_referee(value: Any) -> str | None:
    if not value:
        return None
    return re.sub(r",\s*Mexico$", "", str(value).strip(), flags=re.I).strip() or None


def match_referee(api_name: str | None, refs: dict[str, Any]) -> tuple[str | None, float]:
    if not api_name:
        return None, 0.0
    target = norm(api_name)
    exact = [name for name in refs if norm(name) == target]
    if exact:
        return max(exact, key=lambda n: int(refs[n].get("n") or 0)), 1.0

    tset = {x for x in target.split() if len(x) > 1}
    best_name, best_score = None, 0.0
    for name, row in refs.items():
        if row.get("avg_fouls") is None and row.get("avg_yellow") is None:
            continue
        candidate = norm(name)
        cset = {x for x in candidate.split() if len(x) > 1}
        if not tset or not cset:
            continue
        overlap = len(tset & cset)
        union = len(tset | cset)
        score = overlap / union if union else 0.0
        if target in candidate or candidate in target:
            score = max(score, 0.82)
        if target.split()[-1:] == candidate.split()[-1:]:
            score += 0.12
        if score > best_score:
            best_name, best_score = name, score

    if best_score < 0.45:
        return None, best_score
    return best_name, min(best_score, 1.0)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 4 or len(xs) != len(ys):
        return None
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sx = math.sqrt(sum(x * x for x in dx))
    sy = math.sqrt(sum(y * y for y in dy))
    if sx <= 0 or sy <= 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / (sx * sy)


def model_team_name(api_name: str, teams: dict[str, Any]) -> str | None:
    aliases = {
        "Club America": "América",
        "America": "América",
        "CF Monterrey": "Monterrey",
    }
    mapped = aliases.get(api_name, api_name)
    if mapped in teams:
        return mapped
    target = norm(mapped)
    for name in teams:
        if norm(name) == target:
            return name
    return None


def projected_total(model: dict[str, Any], stat: str, home: str, away: str) -> float:
    w = float(model.get("shrinkage", {}).get(stat, 0.5))
    lg = model["league"][stat]
    th = model["teams"][home]
    ta = model["teams"][away]
    mh = float(th["home"][stat]["for"]) * (float(ta["away"][stat]["against"]) / float(lg["home"]))
    ma = float(ta["away"][stat]["for"]) * (float(th["home"][stat]["against"]) / float(lg["away"]))
    h = w * mh + (1.0 - w) * float(lg["home"])
    a = w * ma + (1.0 - w) * float(lg["away"])
    adj = model.get("season_adj", {}).get(stat)
    if adj is not None:
        h *= float(adj)
        a *= float(adj)
    return h + a


def contextual_multiplier(history_avg, history_n, ref_avg, ref_n, league_avg):
    if not league_avg or league_avg <= 0:
        return 1.0, {"history_component": 1.0, "referee_component": 1.0}

    hist_component = 1.0
    if history_avg is not None and history_n > 0:
        ratio = history_avg / league_avg
        reliability = history_n / (history_n + 8.0)
        hist_component = 1.0 + reliability * (ratio - 1.0)

    ref_component = 1.0
    if ref_avg is not None and ref_n > 0:
        ratio = ref_avg / league_avg
        reliability = ref_n / (ref_n + 12.0)
        ref_component = 1.0 + reliability * (ratio - 1.0)

    multiplier = math.sqrt(max(0.01, hist_component * ref_component)) if ref_avg is not None and ref_n > 0 else hist_component
    multiplier = min(1.25, max(0.80, multiplier))
    return multiplier, {
        "history_component": round(hist_component, 4),
        "referee_component": round(ref_component, 4),
    }


def build_derby(client, fixture, derby, model, target, h2h_last):
    fid = int(fixture["fixture"]["id"])
    home_api = str(fixture["teams"]["home"]["name"])
    away_api = str(fixture["teams"]["away"]["name"])
    home_id = int(fixture["teams"]["home"]["id"])
    away_id = int(fixture["teams"]["away"]["id"])
    home = model_team_name(home_api, model["teams"])
    away = model_team_name(away_api, model["teams"])
    if not home or not away:
        raise RuntimeError(f"Could not map teams for {home_api} vs {away_api}")

    h2h = cached(
        client,
        "ligamx_derby_h2h",
        f"{home_id}_{away_id}_last{h2h_last}",
        "fixtures",
        h2h=f"{home_id}-{away_id}",
        last=h2h_last,
        timezone=TZ,
    )
    h2h = [
        row for row in h2h
        if row.get("fixture", {}).get("status", {}).get("short") in COMPLETED
        and local_day(row["fixture"]["date"]) < target
    ]
    h2h.sort(key=lambda x: parse_dt(x["fixture"]["date"]))

    samples, foul_values, yellow_values = [], [], []
    paired_fouls, paired_yellows = [], []

    for row in h2h:
        hid = int(row["teams"]["home"]["id"])
        aid = int(row["teams"]["away"]["id"])
        parsed = fixture_stats(client, int(row["fixture"]["id"]))
        hs, av = parsed.get(hid, {}), parsed.get(aid, {})
        fouls = float(hs["fouls"]) + float(av["fouls"]) if hs.get("fouls") is not None and av.get("fouls") is not None else None
        yellow = float(hs["yellow"]) + float(av["yellow"]) if hs.get("yellow") is not None and av.get("yellow") is not None else None
        if fouls is not None:
            foul_values.append(fouls)
        if yellow is not None:
            yellow_values.append(yellow)
        if fouls is not None and yellow is not None:
            paired_fouls.append(fouls)
            paired_yellows.append(yellow)
        samples.append({
            "fixture_id": int(row["fixture"]["id"]),
            "date": local_day(row["fixture"]["date"]).isoformat(),
            "home": row["teams"]["home"]["name"],
            "away": row["teams"]["away"]["name"],
            "fouls": fouls,
            "yellow": yellow,
        })

    refs = model.get("referees", {})
    current_ref = clean_referee(fixture.get("fixture", {}).get("referee"))
    matched_ref, match_conf = match_referee(current_ref, refs)
    ref_data = refs.get(matched_ref, {}) if matched_ref else {}

    league_ref = model.get("meta", {}).get("referee_api", {})
    league_yellow = league_ref.get("league_avg_yellow")
    league_fouls = league_ref.get("league_avg_fouls")
    h2h_y = statistics.fmean(yellow_values) if yellow_values else None
    h2h_f = statistics.fmean(foul_values) if foul_values else None

    y_mult, y_parts = contextual_multiplier(
        h2h_y, len(yellow_values), ref_data.get("avg_yellow"),
        int(ref_data.get("n_yellow") or ref_data.get("n") or 0), league_yellow
    )
    f_mult, f_parts = contextual_multiplier(
        h2h_f, len(foul_values), ref_data.get("avg_fouls"),
        int(ref_data.get("n_fouls") or ref_data.get("n") or 0), league_fouls
    )

    base_y = projected_total(model, "Yellow", home, away)
    base_f = projected_total(model, "Fouls", home, away)
    corr = pearson(paired_fouls, paired_yellows)

    return {
        "fixture_id": fid,
        "derby": derby["name"],
        "slug": derby["slug"],
        "home": home,
        "away": away,
        "source": "API-Football H2H + V30 referee table + V30 team model",
        "history": {
            "matches": len(samples),
            "yellow_n": len(yellow_values),
            "fouls_n": len(foul_values),
            "avg_yellow": None if h2h_y is None else round(h2h_y, 2),
            "avg_fouls": None if h2h_f is None else round(h2h_f, 2),
            "fouls_yellow_correlation": None if corr is None else round(corr, 3),
            "samples": samples,
        },
        "referee": {
            "fixture_referee": current_ref,
            "matched_model_referee": matched_ref,
            "match_confidence": round(match_conf, 3),
            "avg_yellow": ref_data.get("avg_yellow"),
            "avg_fouls": ref_data.get("avg_fouls"),
            "n": ref_data.get("n"),
            "n_yellow": ref_data.get("n_yellow"),
            "n_fouls": ref_data.get("n_fouls"),
            "source": ref_data.get("source"),
        },
        "league_reference": {
            "avg_yellow": league_yellow,
            "avg_fouls": league_fouls,
        },
        "model": {
            "base_yellow_mean": round(base_y, 3),
            "base_fouls_mean": round(base_f, 3),
            "yellow_multiplier": round(y_mult, 4),
            "fouls_multiplier": round(f_mult, 4),
            "context_yellow_mean": round(base_y * y_mult, 3),
            "context_fouls_mean": round(base_f * f_mult, 3),
            "yellow_components": y_parts,
            "fouls_components": f_parts,
            "policy": "H2H and referee effects reliability-shrunk toward league average and capped at +/-25%.",
        },
    }


def patch_html(html: str) -> str:
    if "function derbyContextCard(home,away)" not in html:
        helper = r"""
function derbyContextForFixture(){
  var root=M.derby_context;
  if(!root||!root.fixtures||!window.__apiFixtureId) return null;
  return root.fixtures[String(window.__apiFixtureId)]||null;
}
function derbyCandidate(stat,mean,r){
  var b=lambdas(stat,homeSel.value,awaySel.value);
  var base=b.h+b.a;
  var k=base>0?mean/base:1;
  var d=conv(dist(b.h*k,r),dist(b.a*k,r));
  var center=defLine(mean);
  var candidates=[];
  [center-1,center,center+1].forEach(function(line){
    if(line<0.5) return;
    var po=pOver(d,line);
    [{side:'Más de',p:po},{side:'Menos de',p:1-po}].forEach(function(x){
      if(x.p>=0.54&&x.p<=0.72) candidates.push({stat:stat,line:line,side:x.side,p:x.p,fair:1/x.p});
    });
  });
  candidates.sort(function(a,b){return b.p-a.p;});
  return candidates.length?candidates[0]:null;
}
function derbyContextCard(home,away){
  var d=derbyContextForFixture();
  if(!d) return '';
  var h=d.history||{}, r=d.referee||{}, m=d.model||{}, lg=d.league_reference||{};
  var yellow=derbyCandidate('Yellow',m.context_yellow_mean,M.league.Yellow.r);
  var fouls=derbyCandidate('Fouls',m.context_fouls_mean,M.league.Fouls.r);
  var fmt=function(x){return x==null?'—':Number(x).toFixed(2);};
  var corr=h.fouls_yellow_correlation==null?'—':Number(h.fouls_yellow_correlation).toFixed(2);
  var refName=r.fixture_referee||r.matched_model_referee||'pendiente';
  var row=function(x){
    if(!x) return '';
    var label=x.stat==='Yellow'?'amarillas':'faltas';
    return '<div class="lineRow" style="grid-template-columns:1fr auto;margin-top:7px">'+
      '<div style="font-size:.84rem">'+x.side+' '+x.line+' '+label+'</div>'+
      '<div class="odd fav" style="min-width:88px"><div class="px cond">'+x.fair.toFixed(2)+'</div><div class="pc">'+(x.p*100).toFixed(0)+'%</div></div>'+
      '</div>';
  };
  return '<div class="ticket" style="border-color:var(--amber-dim);background:#201b12">'+
    '<div class="tHead"><div class="tName">🔥 '+d.derby+' · contexto disciplinario</div><div class="tLam">API-Football + V30</div></div>'+
    '<div class="tLam">'+
      'H2H ('+(h.matches||0)+'): <b>'+fmt(h.avg_yellow)+'</b> amarillas · <b>'+fmt(h.avg_fouls)+'</b> faltas'+
      ' · liga: '+fmt(lg.avg_yellow)+' / '+fmt(lg.avg_fouls)+
      ' · corr faltas↔amarillas: <b>'+corr+'</b><br>'+
      'Árbitro: <b>'+refName+'</b> · '+fmt(r.avg_yellow)+' amarillas · '+fmt(r.avg_fouls)+' faltas · n='+(r.n||0)+'<br>'+
      'V30 base → contexto: amarillas <b>'+fmt(m.base_yellow_mean)+' → '+fmt(m.context_yellow_mean)+'</b>'+
      ' · faltas <b>'+fmt(m.base_fouls_mean)+' → '+fmt(m.context_fouls_mean)+'</b>'+
    '</div>'+row(yellow)+row(fouls)+
    '<div class="tLam" style="margin-top:8px">Overlay contextual con shrinkage por tamaño de muestra; no reemplaza el modelo base ni convierte el edge en validado. Compara la cuota de la casa contra la justa.</div>'+
    '</div>';
}
"""
        html = html.replace("function picksMarkets(home,away){", helper + "\nfunction picksMarkets(home,away){", 1)

    target = "  valueSection(home,away).then(v=>{ const b=document.getElementById('valueBox'); if(b) b.innerHTML=v; });\n  const inBand=(lo,hi)=>C.filter(c=>c.fair>=lo&&c.fair<=hi).sort((x,y)=>y.p-x.p);"
    replacement = "  valueSection(home,away).then(v=>{ const b=document.getElementById('valueBox'); if(b) b.innerHTML=v; });\n  html+=derbyContextCard(home,away);\n  const inBand=(lo,hi)=>C.filter(c=>c.fair>=lo&&c.fair<=hi).sort((x,y)=>y.p-x.p);"
    if target in html:
        html = html.replace(target, replacement, 1)
    elif "html+=derbyContextCard(home,away);" not in html:
        raise RuntimeError("Could not attach derby context card")

    return html


def main() -> None:
    ap = argparse.ArgumentParser(description="Add derby H2H + referee discipline context to V30 picks.")
    ap.add_argument("--date", required=True)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--h2h-last", type=int, default=10)
    ap.add_argument("--html", default="ligamx edge.html")
    args = ap.parse_args()

    target = date.fromisoformat(args.date)
    html_path = ROOT / args.html
    client = APIFootballClient()

    fixtures = client.fixtures(
        league=LEAGUE_ID, season=args.season, date=target.isoformat(), timezone=TZ
    ).response

    html = html_path.read_text(encoding="utf-8")
    models, start, end = extract_models(html)
    liga = models["ligamx"]

    context = {
        "source": "API-Football",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "date": target.isoformat(),
        "policy": "Derby discipline overlay using H2H yellow/foul history plus assigned-referee averages with reliability shrinkage.",
        "fixtures": {},
    }

    for fx in fixtures:
        pair = frozenset((str(fx["teams"]["home"]["name"]), str(fx["teams"]["away"]["name"])))
        derby = DERBIES.get(pair)
        if not derby:
            continue
        print(f"Building {derby['name']}: {fx['teams']['home']['name']} vs {fx['teams']['away']['name']}")
        d = build_derby(client, fx, derby, liga, target, args.h2h_last)
        context["fixtures"][str(d["fixture_id"])] = d
        print(
            f"  H2H n={d['history']['matches']} | yellow={d['history']['avg_yellow']} | "
            f"fouls={d['history']['avg_fouls']} | corr={d['history']['fouls_yellow_correlation']}"
        )
        print(
            f"  referee={d['referee']['fixture_referee'] or 'pending'} | "
            f"yellow={d['referee']['avg_yellow']} | fouls={d['referee']['avg_fouls']} | n={d['referee']['n']}"
        )
        print(
            f"  V30 -> context: yellow {d['model']['base_yellow_mean']} -> {d['model']['context_yellow_mean']} | "
            f"fouls {d['model']['base_fouls_mean']} -> {d['model']['context_fouls_mean']}"
        )

    if not context["fixtures"]:
        raise SystemExit("No configured derby fixtures found for this date.")

    liga["derby_context"] = context
    liga["meta"]["derby_context_source"] = "API-Football H2H + referee table"
    liga["meta"]["derby_context_captured_at"] = context["captured_at"]

    html = html[:start] + json.dumps(models, ensure_ascii=False, separators=(",", ":")) + html[end:]
    html = patch_html(html)
    html_path.write_text(html, encoding="utf-8")

    export_html = ROOT / "exports" / "LigaMX_Edge_V30.html"
    export_html.write_text(html, encoding="utf-8")

    audit = ROOT / "exports" / f"ligamx_derby_context_{target.isoformat().replace('-', '_')}.json"
    audit.write_text(json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print()
    print(f"Derby contexts embedded: {len(context['fixtures'])}")
    print(f"Updated HTML: {html_path}")
    print(f"Updated export: {export_html}")
    print(f"Audit JSON: {audit}")


if __name__ == "__main__":
    main()

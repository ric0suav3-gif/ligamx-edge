from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.api_football import APIFootballClient
from ingest.cache import save_json

TZ = "America/Mexico_City"
LEAGUE_ID = 262
MARKER = "const MODELS = "


def extract_models(html: str) -> tuple[dict[str, Any], int, int]:
    i = html.find(MARKER)
    if i < 0:
        raise RuntimeError("MODELS object not found")
    start = i + len(MARKER)
    while start < len(html) and html[start].isspace():
        start += 1
    models, used = json.JSONDecoder().raw_decode(html[start:])
    return models, start, start + used


def dec(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x > 1.0 else None


def normalize_odds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    markets: dict[tuple[str, str], dict[str, Any]] = {}
    updates: list[str] = []

    for row in rows:
        if row.get("update"):
            updates.append(str(row["update"]))
        for book in row.get("bookmakers", []):
            book_name = str(book.get("name") or book.get("id") or "Unknown")
            book_id = book.get("id")
            for bet in book.get("bets", []):
                bet_id = str(bet.get("id") or "")
                name = str(bet.get("name") or "").strip()
                key = (bet_id, name)
                market = markets.setdefault(
                    key,
                    {
                        "bet_id": bet.get("id"),
                        "name": name,
                        "outcomes": {},
                    },
                )
                for item in bet.get("values", []):
                    odd = dec(item.get("odd"))
                    value = str(item.get("value") or "").strip()
                    if odd is None or not value:
                        continue
                    market["outcomes"].setdefault(value, []).append(
                        {
                            "bookmaker": book_name,
                            "bookmaker_id": book_id,
                            "odd": round(odd, 4),
                        }
                    )

    serial_markets: list[dict[str, Any]] = []
    for market in markets.values():
        outcomes: list[dict[str, Any]] = []
        for value, quotes in market["outcomes"].items():
            odds = [q["odd"] for q in quotes]
            if not odds:
                continue
            med = statistics.median(odds)
            best = max(odds)
            best_books = sorted(
                {q["bookmaker"] for q in quotes if abs(q["odd"] - best) < 1e-9}
            )
            outcomes.append(
                {
                    "value": value,
                    "book_count": len({q["bookmaker"] for q in quotes}),
                    "consensus_odd": round(float(med), 4),
                    "best_odd": round(float(best), 4),
                    "best_bookmakers": best_books,
                    "quotes": sorted(quotes, key=lambda q: (-q["odd"], q["bookmaker"])),
                }
            )
        if outcomes:
            outcomes.sort(key=lambda x: x["value"].lower())
            serial_markets.append(
                {
                    "bet_id": market["bet_id"],
                    "name": market["name"],
                    "outcomes": outcomes,
                }
            )

    serial_markets.sort(key=lambda x: (str(x["name"]).lower(), str(x["bet_id"])))
    return {
        "market_count": len(serial_markets),
        "latest_provider_update": max(updates) if updates else None,
        "markets": serial_markets,
    }


def patch_html(html: str) -> str:
    old = """  if(window.__fixtureSource==='API-Football'){
    return '<div class="ticket"><div class="tName">API-Football · fixture '+window.__apiFixtureId+'</div><div class="tLam">Slate verificado por API-Football. Esta copia V30 conserva el modelo histórico completo para cuotas justas. Momios/stat layer frescos no se incrustan hasta que termine el collector; compáralos contra la cuota justa antes de apostar.</div></div>';
  }"""

    new = """  if(window.__fixtureSource==='API-Football'){
    return apiOddsSection(home,away);
  }"""

    if old in html:
        html = html.replace(old, new, 1)
    elif "return apiOddsSection(home,away);" not in html:
        raise RuntimeError("Could not patch API-Football value section.")

    helper_marker = "async function valueSection(home,away){"
    if "function apiOddsSection(home,away)" not in html:
        helper = r'''
function apiModelProbForQuote(marketName,value,home,away){
  const n=String(marketName||'').toLowerCase();
  const v=String(value||'').toLowerCase();

  if(n.includes('match winner') || n==='1x2' || n.includes('fulltime result') || n.includes('full time result')){
    const {h,a,r}=lambdas('Goals',home,away);
    const dh=dist(h,r), da=dist(a,r);
    let pH=0,pD=0,pA=0;
    for(let i=0;i<dh.length;i++) for(let j=0;j<da.length;j++){
      const p=dh[i]*da[j];
      if(i>j) pH+=p; else if(i===j) pD+=p; else pA+=p;
    }
    if(v==='home' || v===String(home).toLowerCase()) return pH;
    if(v==='draw' || v==='x') return pD;
    if(v==='away' || v===String(away).toLowerCase()) return pA;
  }

  if(n.includes('double chance')){
    const {h,a,r}=lambdas('Goals',home,away);
    const dh=dist(h,r), da=dist(a,r);
    let pH=0,pD=0,pA=0;
    for(let i=0;i<dh.length;i++) for(let j=0;j<da.length;j++){
      const p=dh[i]*da[j];
      if(i>j) pH+=p; else if(i===j) pD+=p; else pA+=p;
    }
    if(v.includes('home')&&v.includes('draw')) return pH+pD;
    if(v.includes('away')&&v.includes('draw')) return pA+pD;
    if(v.includes('home')&&v.includes('away')) return pH+pA;
  }

  if(n.includes('handicap')) return null;

  let stat=null;
  if(n.includes('shot on target') || n.includes('shots on target') || n.includes('shot on goal') || n.includes('shots on goal')) stat='Shots on Target';
  else if(n.includes('corner')) stat='Corners';
  else if(n.includes('offside')) stat='Offsides';
  else if(n.includes('foul')) stat='Fouls';
  else if(n.includes('yellow')) stat='Yellow';
  else if(n.includes('card')) stat='Cards';
  else if(n.includes('shot')) stat='Shots';
  else if(n.includes('goal') || n.includes('total')) stat='Goals';

  if(!stat || !M.league[stat]) return null;
  const m=v.match(/\b(over|under)\s*([0-9]+(?:\.[0-9]+)?)/i);
  if(!m) return null;
  const side=m[1].toLowerCase(), line=parseFloat(m[2]);
  if(!isFinite(line)) return null;

  const {h,a,r}=lambdas(stat,home,away);
  let d;
  if(n.includes('home team') || n.includes('home total')) d=dist(h,r);
  else if(n.includes('away team') || n.includes('away total')) d=dist(a,r);
  else d=conv(dist(h,r),dist(a,r));

  const po=pOver(d,line);
  return side==='over' ? po : 1-po;
}

function apiOddsSection(home,away){
  const snap=M.api_odds;
  const fx=snap&&snap.fixtures?snap.fixtures[String(window.__apiFixtureId)]:null;
  if(!fx){
    return '<div class="ticket"><div class="tName">API-Football odds</div><div class="tLam">No sportsbook odds were returned for this fixture in the latest refresh.</div></div>';
  }

  const rows=[];
  for(const market of (fx.markets||[])){
    for(const q of (market.outcomes||[])){
      const p=apiModelProbForQuote(market.name,q.value,home,away);
      if(p==null || p<=0 || p>=1) continue;
      const ref=(q.book_count>=2?q.consensus_odd:q.best_odd);
      if(!ref) continue;
      rows.push({
        market:market.name,
        value:q.value,
        p,
        fair:1/p,
        ref,
        best:q.best_odd,
        books:q.book_count||0,
        bestBooks:q.best_bookmakers||[],
        edge:ref*p-1
      });
    }
  }
  rows.sort((a,b)=>b.edge-a.edge);

  const supported=rows.length ? rows.slice(0,14).map(x=>{
    const positive=x.edge>0.02;
    const edgeTxt=(x.edge>=0?'+':'')+(x.edge*100).toFixed(1)+'%';
    const bestBook=x.bestBooks.length?x.bestBooks.slice(0,2).join(', '):'';
    return '<div class="ticket">'+
      '<div class="tHead"><div class="tName">'+(positive?'🟢 ':'')+x.value+'</div><div class="tLam">'+x.market+'</div></div>'+
      '<div class="h4col">'+
        '<div class="odd"><div class="lab">Modelo</div><div class="px cond">'+(x.p*100).toFixed(1)+'%</div><div class="pc">prob.</div></div>'+
        '<div class="odd"><div class="lab">Justa</div><div class="px cond">'+x.fair.toFixed(2)+'</div><div class="pc">sin margen</div></div>'+
        '<div class="odd '+(positive?'fav':'')+'"><div class="lab">Consenso</div><div class="px cond">'+x.ref.toFixed(2)+'</div><div class="pc">'+x.books+' casa'+(x.books===1?'':'s')+'</div></div>'+
        '<div class="odd"><div class="lab">Mejor</div><div class="px cond">'+x.best.toFixed(2)+'</div><div class="pc">'+bestBook+'</div></div>'+
      '</div>'+
      '<div class="tLam" style="margin-top:7px">Edge vs referencia: <b style="color:'+(positive?'#4ade80':'var(--muted)')+'">'+edgeTxt+'</b> · juega solo si tu casa ofrece una cuota superior a la justa.</div>'+
    '</div>';
  }).join('') :
  '<div class="ticket"><div class="tName">Sin mercados comparables</div><div class="tLam">API-Football devolvió odds, pero todavía no hay un mapeo fiable del modelo para esos mercados.</div></div>';

  const meta='<div class="ticket"><div class="tName">API-Football sportsbook snapshot</div>'+
    '<div class="tLam">'+fx.market_count+' mercados · '+fx.bookmaker_count+' casas'+
    (fx.latest_provider_update?' · update '+fx.latest_provider_update:'')+
    '<br>Consenso = mediana entre casas cuando hay 2+. Mejor = mejor precio disponible en el snapshot. 🟢 = edge de modelo &gt;2%, no edge validado.</div></div>';

  return meta+supported;
}
'''
        html = html.replace(helper_marker, helper + "\n" + helper_marker, 1)

    init_old = """try { M = JSON.parse(localStorage.getItem('lmxModel_'+CUR_LEAGUE)) || EMBEDDED; }
catch(e){ M = EMBEDDED; }

let STATS = M.meta.stats;"""
    init_new = """try { M = JSON.parse(localStorage.getItem('lmxModel_'+CUR_LEAGUE)) || EMBEDDED; }
catch(e){ M = EMBEDDED; }
// Keep the fresh embedded sportsbook snapshot even if an older model is cached in localStorage.
if(M && EMBEDDED && EMBEDDED.api_odds && !M.api_odds) M.api_odds=EMBEDDED.api_odds;

let STATS = M.meta.stats;"""
    if init_old in html:
        html = html.replace(init_old, init_new, 1)

    switch_old = """  try{ M = JSON.parse(localStorage.getItem('lmxModel_'+lg)) || MODELS[lg]; }
  catch(e){ M = MODELS[lg]; }
  STATS = M.meta.stats;"""
    switch_new = """  try{ M = JSON.parse(localStorage.getItem('lmxModel_'+lg)) || MODELS[lg]; }
  catch(e){ M = MODELS[lg]; }
  if(M && MODELS[lg] && MODELS[lg].api_odds && !M.api_odds) M.api_odds=MODELS[lg].api_odds;
  STATS = M.meta.stats;"""
    if switch_old in html:
        html = html.replace(switch_old, switch_new, 1)

    return html


def main() -> None:
    ap = argparse.ArgumentParser(description="Embed current API-Football sportsbook odds into Liga MX Edge V30.")
    ap.add_argument("--date", required=True)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--html", default="ligamx edge.html")
    args = ap.parse_args()

    target = date.fromisoformat(args.date)
    html_path = ROOT / args.html
    if not html_path.exists():
        raise SystemExit(f"Missing HTML: {html_path}")

    client = APIFootballClient()
    fixtures = client.fixtures(
        league=LEAGUE_ID,
        season=args.season,
        date=target.isoformat(),
        timezone=TZ,
    ).response
    if not fixtures:
        raise SystemExit(f"No Liga MX fixtures returned for {target}.")

    html = html_path.read_text(encoding="utf-8")
    models, start, end = extract_models(html)
    liga = models["ligamx"]

    snapshot = {
        "source": "API-Football",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "date": target.isoformat(),
        "season": args.season,
        "league_id": LEAGUE_ID,
        "reference_policy": "median consensus when 2+ books; best price shown separately",
        "fixtures": {},
    }

    export = {
        "meta": {k: snapshot[k] for k in ("source", "captured_at", "date", "season", "league_id", "reference_policy")},
        "fixtures": {},
    }

    for fx in fixtures:
        fid = int(fx["fixture"]["id"])
        home = fx["teams"]["home"]["name"]
        away = fx["teams"]["away"]["name"]
        print(f"Fetching odds: {home} vs {away} | fixture {fid}")

        rows = client.odds(fixture=fid).response
        save_json("odds_live", f"fixture_{fid}_{target.isoformat()}", rows)
        norm = normalize_odds(rows)

        books = set()
        for market in norm["markets"]:
            for outcome in market["outcomes"]:
                for q in outcome["quotes"]:
                    books.add(q["bookmaker"])

        payload = {
            "fixture_id": fid,
            "home": home,
            "away": away,
            "bookmaker_count": len(books),
            **norm,
        }
        snapshot["fixtures"][str(fid)] = payload
        export["fixtures"][str(fid)] = payload
        print(f"  {norm['market_count']} markets | {len(books)} bookmakers")

    liga["api_odds"] = snapshot
    liga["meta"]["odds_source"] = "API-Football"
    liga["meta"]["odds_captured_at"] = snapshot["captured_at"]

    html = html[:start] + json.dumps(models, ensure_ascii=False, separators=(",", ":")) + html[end:]
    html = patch_html(html)
    html_path.write_text(html, encoding="utf-8")

    export_dir = ROOT / "exports"
    export_dir.mkdir(exist_ok=True)
    export_html = export_dir / "LigaMX_Edge_V30.html"
    export_html.write_text(html, encoding="utf-8")

    odds_file = export_dir / f"ligamx_odds_{target.isoformat().replace('-', '_')}.json"
    odds_file.write_text(json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    total_markets = sum(x["market_count"] for x in snapshot["fixtures"].values())
    total_books = len({q["bookmaker"] for f in snapshot["fixtures"].values() for m in f["markets"] for o in m["outcomes"] for q in o["quotes"]})
    print()
    print(f"Embedded odds into: {html_path}")
    print(f"Updated export HTML: {export_html}")
    print(f"Odds audit export: {odds_file}")
    print(f"Fixtures: {len(snapshot['fixtures'])} | markets: {total_markets} | unique bookmakers: {total_books}")
    print("No API key or secret is embedded in the HTML/JSON.")


if __name__ == "__main__":
    main()

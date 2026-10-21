"""Build the next-games edge card: model projections, Polymarket 1X2 and liguilla stakes.

    python scripts/edge_card.py --from 2026-10-20 --to 2026-10-21

Reads the model embedded in index.html (same numbers the page shows), fixtures
from data/ligamx_espn_latest.json and Polymarket prices from the newest
data/polymarket_*.json. Writes tracking/edge-card-<from>.md.

Prices here are fair prices (no margin). A prop is only a bet if the book pays
more than the fair price shown, with some cushion for model error.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Mexico_City")
W_MARKET_DEEP, W_MARKET_THIN, DEEP_LIQ = 0.70, 0.50, 50000


def load_model() -> dict:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r"^const MODELS = (.+);$", html, re.MULTILINE).group(1))["ligamx"]


def distribution(mean: float, r: float | None) -> list[float]:
    sd = math.sqrt(mean if r is None else mean + mean * mean / r)
    top = max(12, math.ceil(mean + 8 * sd))
    out = []
    for k in range(top + 1):
        if r is None:
            p = math.exp(-mean + k * math.log(mean) - math.lgamma(k + 1))
        else:
            pp = r / (r + mean)
            p = math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(pp) + k * math.log(1 - pp))
        out.append(p)
    s = sum(out)
    return [x / s for x in out]


def conv(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def p_over(d: list[float], line: float) -> float:
    return sum(d[math.floor(line) + 1:])


def rates(model: dict, stat: str, home: str, away: str, motivation: bool = True) -> tuple[float, float, float | None]:
    lg = model["league"][stat]
    w = model["shrinkage"].get(stat, 0.5)
    th, ta = model["teams"][home]["home"][stat], model["teams"][away]["away"][stat]
    h = th["for"] * (ta["against"] / lg["home"])
    a = ta["for"] * (th["against"] / lg["away"])
    adj = model.get("season_adj", {}).get(stat, 1)
    h, a = (w * h + (1 - w) * lg["home"]) * adj, (w * a + (1 - w) * lg["away"]) * adj
    st = (model.get("stakes") or {}).get("teams", {})
    if motivation and stat == "Goals" and st:
        k = model["stakes"].get("k_goals", 0.06)
        mh, ma = st.get(home, {}).get("motivation", 0), st.get(away, {}).get("motivation", 0)
        h, a = h * (1 + k * (mh - ma)), a * (1 + k * (ma - mh))
    return h, a, lg["r"]


def one_x_two(model: dict, home: str, away: str, motivation: bool = True) -> dict:
    h, a, r = rates(model, "Goals", home, away, motivation)
    dh, da = distribution(h, r), distribution(a, r)
    ph = sum(dh[i] * sum(da[:i]) for i in range(len(dh)))
    pd = sum(dh[i] * da[i] for i in range(min(len(dh), len(da))))
    return {"H": ph, "D": pd, "A": 1 - ph - pd}


def default_line(x: float) -> float:
    return max(0.5, round(x - 0.5) + 0.5)


def fmt_pct(p: float) -> str:
    return f"{p * 100:.0f}%"


def card(model: dict, fx: dict, pm: dict | None) -> tuple[str, list[dict]]:
    home, away = fx["home"], fx["away"]
    kick = datetime.fromisoformat(fx["kickoff"].replace("Z", "+00:00")).astimezone(TZ)
    st = (model.get("stakes") or {}).get("teams", {})
    mo = one_x_two(model, home, away)
    mo_flat = one_x_two(model, home, away, motivation=False)
    lines = [f"### {home} vs {away} — {kick:%a %d %b %H:%M} CDMX", ""]
    for t in (home, away):
        s = st.get(t)
        if s:
            lines.append(f"- **{t}**: {s['pts']} pts ({s['gp']} PJ) · top 8 {fmt_pct(s['p_top8'])} · si gana {fmt_pct(s['p_top8_if_win'] or 0)} / si pierde {fmt_pct(s['p_top8_if_loss'] or 0)} · motivación {s['motivation']:.2f}")
    k = model.get("stakes", {}).get("k_goals", 0.06)
    gap = st.get(home, {}).get("motivation", 0) - st.get(away, {}).get("motivation", 0)
    if abs(gap) >= 0.05:
        lines.append(f"- Motivation shift on goals: {home} {k * gap * 100:+.1f}%, {away} {-k * gap * 100:+.1f}% (moves home win {100 * (mo['H'] - mo_flat['H']):+.1f} pts)")
    lines.append("")
    leans: list[dict] = []
    lines.append("| 1X2 | Home | Draw | Away |")
    lines.append("| --- | ---: | ---: | ---: |")
    lines.append(f"| Model | {fmt_pct(mo['H'])} | {fmt_pct(mo['D'])} | {fmt_pct(mo['A'])} |")
    if pm:
        tot = pm["H"] + pm["D"] + pm["A"]
        pmn = {x: pm[x] / tot for x in "HDA"}
        w = W_MARKET_DEEP if pm.get("liquidity", 0) >= DEEP_LIQ else W_MARKET_THIN
        bl = {x: w * pmn[x] + (1 - w) * mo[x] for x in "HDA"}
        lines.append(f"| Polymarket (liq ${pm.get('liquidity', 0)/1000:.0f}k) | {fmt_pct(pmn['H'])} | {fmt_pct(pmn['D'])} | {fmt_pct(pmn['A'])} |")
        lines.append(f"| **Blend ({int(w*100)}% mkt)** | **{fmt_pct(bl['H'])}** | **{fmt_pct(bl['D'])}** | **{fmt_pct(bl['A'])}** |")
        lines.append(f"| Fair odds (blend) | {1/bl['H']:.2f} | {1/bl['D']:.2f} | {1/bl['A']:.2f} |")
        names = {"H": home, "D": "Draw", "A": away}
        for x in "HDA":
            diff = mo[x] - pmn[x]
            if abs(diff) >= 0.06:
                leans.append({"market": f"1X2 {names[x]}", "side": "model higher" if diff > 0 else "model lower", "p": bl[x], "fair": 1 / bl[x], "note": f"model {fmt_pct(mo[x])} vs Polymarket {fmt_pct(pmn[x])}"})
    else:
        lines.append("| Polymarket | — | — | — |")
    lines.append("")
    lines.append("| Stat | Home exp | Away exp | Total | Line | Over % | Fair O | Fair U |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for stat in ("Goals", "Shots", "Shots on Target", "Corners", "Fouls", "Cards", "Offsides"):
        h, a, r = rates(model, stat, home, away)
        td = conv(distribution(h, r), distribution(a, r))
        line = default_line(h + a)
        po = p_over(td, line)
        lines.append(f"| {stat} | {h:.2f} | {a:.2f} | {h + a:.2f} | {line} | {po*100:.0f}% | {1/po:.2f} | {1/(1-po):.2f} |")
    lines.append("")
    lines.append("Team totals (fair O / U at the usual book line):")
    tt = []
    for stat, ln in (("Goals", 1.5), ("Shots", 12.5), ("Shots on Target", 4.5), ("Corners", 4.5)):
        h, a, r = rates(model, stat, home, away)
        ph, pa = p_over(distribution(h, r), ln), p_over(distribution(a, r), ln)
        tt.append(f"{stat} {ln}: {home} O {1/ph:.2f} / U {1/(1-ph):.2f} · {away} O {1/pa:.2f} / U {1/(1-pa):.2f}")
    lines += [f"- {x}" for x in tt]
    lines.append("")
    return "\n".join(lines), leans


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--include-started", action="store_true", help="keep games whose kickoff has already passed")
    args = ap.parse_args()
    now = datetime.now(TZ)
    model = load_model()
    snap = json.loads((ROOT / "data" / "ligamx_espn_latest.json").read_text(encoding="utf-8"))
    pm_files = sorted((ROOT / "data").glob("polymarket_*.json"))
    pm_data = json.loads(pm_files[-1].read_text(encoding="utf-8")) if pm_files else {"games": []}
    pm_by = {(g["home"], g["away"]): g for g in pm_data["games"]}
    fixtures = []
    for f in snap.get("fixtures", []):
        local = datetime.fromisoformat(f["kickoff"].replace("Z", "+00:00")).astimezone(TZ)
        if args.start <= local.date().isoformat() <= args.end and (args.include_started or local > now):
            fixtures.append(f)
    fixtures.sort(key=lambda f: f["kickoff"])
    out = [f"# Liga MX edge card — {args.start} to {args.end}", "",
           f"Model {model['meta']['version']} · data through {model['meta']['date_range'][1]} ({model['meta']['matches']} matches) · stakes as of {model.get('stakes', {}).get('as_of')}",
           f"Polymarket snapshot: {pm_data.get('pulledAtMexico', 'n/a')} (mid prices, normalized).", "",
           "Fair prices carry no margin. Only bet when the book pays more than the fair price, ideally 5%+ more on props.", ""]
    all_leans = []
    for f in fixtures:
        text, leans = card(model, f, pm_by.get((f["home"], f["away"])))
        out.append(text)
        all_leans += [dict(l, match=f"{f['home']}–{f['away']}") for l in leans]
    if all_leans:
        out += ["## Where the model and Polymarket disagree by 6+ points", ""]
        out += [f"- {l['match']}: {l['market']} — {l['note']}; blended {fmt_pct(l['p'])}, fair {l['fair']:.2f}" for l in all_leans]
    path = ROOT / "tracking" / f"edge-card-{args.start}.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()

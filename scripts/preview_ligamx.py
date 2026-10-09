"""Print current no-key model means and fair prices for the two Friday games."""

import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "index.html").read_text(encoding="utf-8")
model = json.loads(re.search(r"^const MODELS = (.+);$", html, re.MULTILINE).group(1))["ligamx"]


def distribution(mean, r):
    sd = math.sqrt(mean if r is None else mean + mean * mean / r)
    top = max(10, math.ceil(mean + 8 * sd))
    values = []
    for k in range(top + 1):
        if r is None:
            p = math.exp(-mean + k * math.log(mean) - math.lgamma(k + 1))
        else:
            pp = r / (r + mean)
            p = math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(pp) + k * math.log(1 - pp))
        values.append(p)
    total = sum(values)
    return [x / total for x in values]


def rates(stat, home, away):
    league = model["league"][stat]
    w = model["shrinkage"].get(stat, 0.5)
    h = model["teams"][home]["home"][stat]["for"] * (model["teams"][away]["away"][stat]["against"] / league["home"])
    a = model["teams"][away]["away"][stat]["for"] * (model["teams"][home]["home"][stat]["against"] / league["away"])
    adj = model.get("season_adj", {}).get(stat, 1)
    return (w * h + (1 - w) * league["home"]) * adj, (w * a + (1 - w) * league["away"]) * adj, league["r"]


def over(d, line):
    return sum(d[math.floor(line) + 1 :])


def total_dist(a, b):
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


for home, away in (("Puebla", "León"), ("Tigres UANL", "Toluca")):
    print(f"\n{home} vs {away}")
    for stat in ("Goals", "Shots", "Shots on Target", "Corners", "Fouls", "Cards", "Offsides"):
        h, a, r = rates(stat, home, away)
        hd, ad = distribution(h, r), distribution(a, r)
        td = total_dist(hd, ad)
        lines = {"Goals": [2.5, 3.5], "Shots": [24.5, 26.5, 28.5], "Shots on Target": [8.5, 9.5], "Corners": [9.5, 10.5, 11.5], "Fouls": [23.5, 24.5], "Cards": [4.5, 5.5], "Offsides": [3.5, 4.5]}[stat]
        print(f"  {stat:16} home={h:5.2f} away={a:5.2f} total={h+a:5.2f}  " + "  ".join(f"O{line}: {over(td,line):.3f} fair {1/over(td,line):.2f}" for line in lines))
    print("  Team totals:")
    for stat, line in (("Goals", 1.5), ("Shots", 12.5), ("Shots on Target", 4.5), ("Corners", 4.5)):
        h, a, r = rates(stat, home, away)
        hp, ap = over(distribution(h, r), line), over(distribution(a, r), line)
        print(f"    {stat:16} O{line}: {home} {hp:.3f} fair {1/hp:.2f}; {away} {ap:.3f} fair {1/ap:.2f}")
    h, a, r = rates("Goals", home, away)
    hd, ad = distribution(h, r), distribution(a, r)
    home_win = sum(hd[i] * sum(ad[:i]) for i in range(len(hd)))
    away_win = sum(ad[j] * sum(hd[:j]) for j in range(len(ad)))
    draw = 1 - home_win - away_win
    print(f"  1X2: {home} {home_win:.3f}, draw {draw:.3f}, {away} {away_win:.3f}; DNB fair {home} {(1-draw)/home_win:.2f}, {away} {(1-draw)/away_win:.2f}")
    for stat in ("Corners", "Shots", "Shots on Target"):
        h, a, r = rates(stat, home, away)
        hd, ad = distribution(h, r), distribution(a, r)
        hw = sum(hd[i] * sum(ad[:i]) for i in range(len(hd)))
        aw = sum(ad[j] * sum(hd[:j]) for j in range(len(ad)))
        tie = 1 - hw - aw
        print(f"  {stat} H2H: {home} {hw:.3f}, tie {tie:.3f}, {away} {aw:.3f}; pk fair {home} {(1-tie)/hw:.2f}, {away} {(1-tie)/aw:.2f}")
        if stat == "Corners":
            for margin in (1, 2, 3):
                p = sum(hd[i] * sum(ad[: max(0, i - margin)]) for i in range(len(hd)))
                print(f"    {home} corners -{margin}.5: p={p:.3f}, fair={1/p:.2f}")

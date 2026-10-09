"""Holdout-check whether 2026 team scoring form improves v30 goal forecasts."""

import math
from collections import defaultdict

from sync_ligamx_espn import fetch, load_base, local_date, name


base = load_base()
league = base["league"]["Goals"]
overall = (league["home"] + league["away"]) / 2
board = fetch("https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard?dates=2026&limit=500")
events = sorted((e for e in board["events"] if e["status"]["type"]["completed"] and "2026-07-01" <= local_date(e) <= "2026-09-27"), key=lambda e: e["date"])
records = defaultdict(lambda: {"n": 0, "gf": 0, "ga": 0})
loss = {w: [0.0, 0] for w in (0, 0.15, 0.25, 0.35, 0.5, 0.65, 0.75)}


def prior(home, away):
    w = base["shrinkage"]["Goals"]
    h = base["teams"][home]["home"]["Goals"]["for"] * base["teams"][away]["away"]["Goals"]["against"] / league["home"]
    a = base["teams"][away]["away"]["Goals"]["for"] * base["teams"][home]["home"]["Goals"]["against"] / league["away"]
    return w * h + (1 - w) * league["home"], w * a + (1 - w) * league["away"]


def season(home, away):
    h, a = records[home], records[away]
    rate = lambda record, key: (record[key] + 4 * overall) / (record["n"] + 4)
    home_rate = league["home"] * rate(h, "gf") / overall * rate(a, "ga") / overall
    away_rate = league["away"] * rate(a, "gf") / overall * rate(h, "ga") / overall
    return home_rate, away_rate


for event in events:
    sides = {x["homeAway"]: x for x in event["competitions"][0]["competitors"]}
    h = name(sides["home"]["team"]["displayName"], base["teams"])
    a = name(sides["away"]["team"]["displayName"], base["teams"])
    if not h or not a:
        continue
    hg, ag = int(sides["home"]["score"]), int(sides["away"]["score"])
    if local_date(event) > base["meta"]["date_range"][1]:
        ph, pa = prior(h, a)
        fh, fa = season(h, a)
        for weight, accum in loss.items():
            mh, ma = (1 - weight) * ph + weight * fh, (1 - weight) * pa + weight * fa
            accum[0] += mh - hg * math.log(mh) + math.lgamma(hg + 1)
            accum[0] += ma - ag * math.log(ma) + math.lgamma(ag + 1)
            accum[1] += 2
    for team, gf, ga in ((h, hg, ag), (a, ag, hg)):
        records[team]["n"] += 1
        records[team]["gf"] += gf
        records[team]["ga"] += ga

for weight, (total, n) in loss.items():
    print(f"season weight {weight:0.2f}: {n//2} games, mean goal NLL {total/n:.4f}")

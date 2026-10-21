"""Liguilla stakes: Monte Carlo of the rest of the regular season.

Format (Apertura 2026, Fox Sports MX 2026-10-15): 17 jornadas, the top 8 of the
general table go straight to the quarterfinals, no play-in. Teams 9+ are out.

For every team we simulate the remaining fixtures with the model's own goal
rates and record:

* p_top8     - probability of finishing in the top 8
* p_top4     - probability of a top-4 seed (second leg at home)
* leverage   - P(top 8 | win next game) - P(top 8 | lose next game)
* motivation - leverage scaled to 0..1 (0.35 swing or more = 1.0)

The page applies a small goals adjustment from the motivation gap between the
two sides (k_goals, default +/-6% at the extremes). That size is a prior, not
something fitted: there is not yet enough match-level history with standings to
estimate it, and earlier checks in this repo found dead-rubber games do not
show lower shot/corner volume, so volume stats are left untouched.
"""

from __future__ import annotations

import math
import random
from datetime import datetime

SIMS = 20000
TOP = 8
LEVERAGE_FULL = 0.35
K_GOALS = 0.06


def goal_rates(model: dict, home: str, away: str) -> tuple[float, float]:
    lg = model["league"]["Goals"]
    w = model["shrinkage"].get("Goals", 0.5)
    th, ta = model["teams"][home]["home"]["Goals"], model["teams"][away]["away"]["Goals"]
    h = th["for"] * (ta["against"] / lg["home"])
    a = ta["for"] * (th["against"] / lg["away"])
    return w * h + (1 - w) * lg["home"], w * a + (1 - w) * lg["away"]


def poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def simulate(model: dict, standings: dict, fixtures: list[dict], sims: int = SIMS, seed: int = 7) -> dict:
    rng = random.Random(seed)
    teams = list(standings)
    rates = [(f["home"], f["away"], *goal_rates(model, f["home"], f["away"])) for f in fixtures]
    first = {}
    for i, f in enumerate(sorted(range(len(fixtures)), key=lambda j: fixtures[j]["kickoff"])):
        for side in ("home", "away"):
            first.setdefault(fixtures[f][side], f)
    top8 = {t: 0 for t in teams}
    top4 = {t: 0 for t in teams}
    cond = {t: {"W": [0, 0], "D": [0, 0], "L": [0, 0]} for t in teams}
    for _ in range(sims):
        pts = {t: standings[t][0] for t in teams}
        gf = {t: standings[t][2] for t in teams}
        ga = {t: standings[t][3] for t in teams}
        outcome = {}
        for idx, (h, a, lh, la) in enumerate(rates):
            hg, ag = poisson(rng, lh), poisson(rng, la)
            gf[h] += hg; ga[h] += ag; gf[a] += ag; ga[a] += hg
            if hg > ag:
                pts[h] += 3; res = ("W", "L")
            elif hg < ag:
                pts[a] += 3; res = ("L", "W")
            else:
                pts[h] += 1; pts[a] += 1; res = ("D", "D")
            if first.get(h) == idx:
                outcome[h] = res[0]
            if first.get(a) == idx:
                outcome[a] = res[1]
        order = sorted(teams, key=lambda t: (pts[t], gf[t] - ga[t], gf[t], rng.random()), reverse=True)
        for rank, t in enumerate(order):
            inside = rank < TOP
            top8[t] += inside
            top4[t] += rank < 4
            if t in outcome:
                c = cond[t][outcome[t]]
                c[0] += inside
                c[1] += 1
    out = {}
    for t in teams:
        c = cond[t]
        pw = c["W"][0] / c["W"][1] if c["W"][1] else None
        pl = c["L"][0] / c["L"][1] if c["L"][1] else None
        lev = (pw - pl) if pw is not None and pl is not None else 0.0
        nxt = next((f for f in sorted(fixtures, key=lambda f: f["kickoff"]) if t in (f["home"], f["away"])), None)
        out[t] = {
            "pts": standings[t][0], "gp": standings[t][1],
            "p_top8": round(top8[t] / sims, 4), "p_top4": round(top4[t] / sims, 4),
            "p_top8_if_win": None if pw is None else round(pw, 4),
            "p_top8_if_loss": None if pl is None else round(pl, 4),
            "leverage": round(max(lev, 0.0), 4),
            "motivation": round(min(1.0, max(lev, 0.0) / LEVERAGE_FULL), 3),
            "next": None if not nxt else (("vs " + nxt["away"]) if nxt["home"] == t else ("@ " + nxt["home"])),
        }
    return out


def attach_stakes(model: dict, standings: dict, fixtures: list[dict], today: str) -> dict:
    fx = [f for f in fixtures if f["home"] in model["teams"] and f["away"] in model["teams"] and f["home"] in standings and f["away"] in standings]
    model["stakes"] = {
        "as_of": today,
        "format": "Apertura 2026: 17 jornadas, top 8 directo a cuartos, sin play-in",
        "sims": SIMS,
        "remaining_fixtures": len(fx),
        "k_goals": K_GOALS,
        "leverage_full": LEVERAGE_FULL,
        "teams": simulate(model, standings, fx) if fx else {},
    }
    return model["stakes"]


def goal_multipliers(stakes: dict | None, home: str, away: str) -> tuple[float, float]:
    """Same formula the page uses: +k*(gap) for the hungrier side, -k*(gap) for the other."""
    if not stakes or not stakes.get("teams"):
        return 1.0, 1.0
    t = stakes["teams"]
    mh, ma = t.get(home, {}).get("motivation", 0.0), t.get(away, {}).get("motivation", 0.0)
    k = stakes.get("k_goals", K_GOALS)
    return 1 + k * (mh - ma), 1 + k * (ma - mh)


if __name__ == "__main__":
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    snap = json.loads((root / "data" / "ligamx_espn_latest.json").read_text(encoding="utf-8"))
    for team, v in sorted((snap.get("stakes") or {}).get("teams", {}).items(), key=lambda kv: -kv[1]["p_top8"]):
        print(f"{team:22} {v['pts']:2} pts  top8 {v['p_top8']:.2f}  lev {v['leverage']:.2f}  mot {v['motivation']:.2f}  {v['next']}")
    print(datetime.now().isoformat())

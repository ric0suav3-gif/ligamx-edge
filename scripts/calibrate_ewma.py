"""Walk-forward negative log likelihood for candidate post-cutoff EWMA speeds."""

import copy
import json
import math
from pathlib import Path

from sync_ligamx_espn import load_base


root = Path(__file__).resolve().parents[1]
base = load_base()
matches = json.loads((root / "data" / "ligamx_espn_latest.json").read_text(encoding="utf-8"))["matches"]
stats = ("Goals", "Shots", "Shots on Target", "Corners", "Fouls", "Offsides", "Cards")
alphas = (0.0, 0.0539, 0.10, 0.15, 0.20, 0.30)


def nll(k, mean, r):
    if r is None:
        return mean - k * math.log(mean) + math.lgamma(k + 1)
    p = r / (r + mean)
    return -(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))


for alpha in alphas:
    model = copy.deepcopy(base)
    scores = {s: [0.0, 0] for s in stats}
    for game in matches:
        home, away = game["home"], game["away"]
        hsplit = model["teams"][home["name"]]["home"]
        asplit = model["teams"][away["name"]]["away"]
        for stat in stats:
            hv, av = home.get(stat), away.get(stat)
            if hv is None or av is None:
                continue
            lg = model["league"][stat]
            w = model["shrinkage"].get(stat, 0.5)
            adj = model.get("season_adj", {}).get(stat, 1)
            hm = (w * hsplit[stat]["for"] * asplit[stat]["against"] / lg["home"] + (1 - w) * lg["home"]) * adj
            am = (w * asplit[stat]["for"] * hsplit[stat]["against"] / lg["away"] + (1 - w) * lg["away"]) * adj
            scores[stat][0] += nll(hv, hm, lg["r"]) + nll(av, am, lg["r"])
            scores[stat][1] += 2
            for split, own, opp in ((hsplit, hv, av), (asplit, av, hv)):
                split[stat]["for"] = (1 - alpha) * split[stat]["for"] + alpha * own
                split[stat]["against"] = (1 - alpha) * split[stat]["against"] + alpha * opp
    print(f"alpha {alpha:0.4f}: " + ", ".join(f"{stat} {scores[stat][0]/scores[stat][1]:.4f}" for stat in stats))

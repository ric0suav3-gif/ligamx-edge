from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from liguilla_stakes import goal_multipliers, simulate  # noqa: E402


def model() -> dict:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r"^const MODELS = (.+);$", html, re.MULTILINE).group(1))["ligamx"]


def test_clinched_and_eliminated_teams_have_no_leverage() -> None:
    m = model()
    teams = list(m["teams"])[:10]
    standings = {t: [20, 16, 10, 10] for t in teams}
    standings[teams[0]] = [60, 16, 40, 5]   # far clear: top 8 locked
    standings[teams[1]] = [0, 16, 0, 40]     # bottom: cannot reach 8th
    fixtures = [{"kickoff": "2026-11-20T01:00Z", "home": teams[0], "away": teams[1]}]
    out = simulate(m, standings, fixtures, sims=2000)
    assert out[teams[0]]["p_top8"] == 1.0 and out[teams[0]]["leverage"] == 0.0
    assert out[teams[1]]["p_top8"] == 0.0 and out[teams[1]]["leverage"] == 0.0


def test_embedded_stakes_are_probabilities_and_sum_to_eight() -> None:
    st = model()["stakes"]["teams"]
    assert all(0 <= v["p_top8"] <= 1 and 0 <= v["motivation"] <= 1 for v in st.values())
    assert abs(sum(v["p_top8"] for v in st.values()) - 8) < 0.01


def test_motivation_multiplier_is_symmetric_and_bounded() -> None:
    stakes = {"k_goals": 0.06, "teams": {"A": {"motivation": 1.0}, "B": {"motivation": 0.0}}}
    h, a = goal_multipliers(stakes, "A", "B")
    assert abs(h - 1.06) < 1e-9 and abs(a - 0.94) < 1e-9
    assert goal_multipliers(None, "A", "B") == (1.0, 1.0)

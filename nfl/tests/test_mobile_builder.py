from pathlib import Path

from nfl.scripts.build_mobile_ui import approximate_moneyline, build_payload


def projection(side: str, name: str, points: float) -> dict:
    return {
        "side": side,
        "team_name": name,
        "expected_plays": 60.0,
        "expected_pass_attempts": 34.0,
        "expected_completions": 22.0,
        "expected_rush_attempts": 26.0,
        "expected_passing_yards": 240.0,
        "expected_rushing_yards": 110.0,
        "expected_sacks_made": 2.0,
        "expected_turnovers": 1.0,
        "expected_points": points,
        "points_sd": 8.0,
        "reliability": "HIGH",
    }


def test_approximate_moneyline_is_complete_and_complementary():
    home = projection("home", "Home", 28.0)
    away = projection("away", "Away", 24.0)
    rows = approximate_moneyline(home, away, 1.55, 2.60)

    assert len(rows) == 2
    assert abs(sum(row["win_prob"] for row in rows) - 1.0) < 1e-12
    assert rows[0]["team"] == "Home"
    assert rows[0]["fair"] > 1.0


def test_payload_orders_markets_by_consensus_ev():
    home = projection("home", "Home", 28.0)
    away = projection("away", "Away", 24.0)
    context = {"histories": {"1": {"matches": [1, 2]}, "2": {"matches": [1, 2]}}}
    comparisons = {"rows": [{"consensus_ev": 0.05}, {"consensus_ev": 0.20}]}

    payload = build_payload(
        game_id="123",
        context=context,
        team_predictions={"projections": [away, home]},
        comparisons=comparisons,
        props={"rows": []},
        date="2026-09-10",
        kickoff="18:35 CDMX",
        venue="Melbourne",
        home_odd=1.55,
        away_odd=2.60,
    )

    assert payload["game"]["total"] == 52.0
    assert payload["team_markets"][0]["consensus_ev"] == 0.20
    assert len(payload["stats"]) == 9


def test_mobile_template_has_ranked_picks_view():
    template = (
        Path(__file__).resolve().parents[1] / "web" / "nfl_mobile_template.html"
    ).read_text(encoding="utf-8")

    assert 'id="picksView"' in template
    assert 'id="navPicks"' in template
    assert "function rankedPicks()" in template
    assert "Ladder 1.60–1.80" in template

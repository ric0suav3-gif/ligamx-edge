from nfl.model.selection import select_straights, select_two_leg_parlays


def market(
    game_id: str,
    *,
    price: float,
    fair: float,
    ev: float,
    line: float = 40.5,
    books: int = 4,
) -> dict:
    return {
        "game_id": game_id,
        "stat": "points",
        "scope": "match_total",
        "side": "over",
        "line": line,
        "median_odd": price,
        "fair": fair,
        "consensus_ev": ev,
        "books": books,
    }


def test_straights_enforce_price_probability_and_one_pick_per_game():
    rows = [
        market("1", price=1.70, fair=1.40, ev=0.12, line=40.5),
        market("1", price=1.75, fair=1.55, ev=0.10, line=42.5),
        market("2", price=1.65, fair=1.50, ev=0.08),
        market("3", price=1.90, fair=1.40, ev=0.20),
        market("4", price=1.70, fair=1.80, ev=0.20),
    ]

    selected = select_straights(rows)

    assert [row["game_id"] for row in selected] == ["1", "2"]
    assert selected[0]["line"] == 40.5


def test_parlays_are_two_separate_games_in_target_band():
    rows = [
        market("1", price=1.30, fair=1.20, ev=0.08),
        market("2", price=1.30, fair=1.25, ev=0.04),
        market("3", price=1.60, fair=1.30, ev=0.10),
    ]

    selected = select_two_leg_parlays(rows)

    assert len(selected) == 1
    assert round(selected[0]["price"], 2) == 1.69
    assert {leg["game_id"] for leg in selected[0]["legs"]} == {"1", "2"}

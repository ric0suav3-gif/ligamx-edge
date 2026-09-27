from nfl.model.distributions import count_fair_price, normal_fair_price
from nfl.model.rushing import project_player_rushing


def sample_game(
    player_attempts: int,
    player_yards: int,
    team_attempts: int = 30,
    team_yards: int = 135,
    opp_attempts: int = 27,
    opp_yards: int = 120,
):
    return {
        "team": {
            "rush_attempts": team_attempts,
            "rushing_yards": team_yards,
        },
        "opponent_team": {
            "rush_attempts": opp_attempts,
            "rushing_yards": opp_yards,
        },
        "players": [
            {
                "player_name": "Test Back",
                "rushing": {
                    "attempts": player_attempts,
                    "yards": player_yards,
                },
            }
        ],
    }


def test_project_player_rushing() -> None:
    own = [
        sample_game(12, 55),
        sample_game(14, 67),
        sample_game(16, 80),
        sample_game(15, 72),
        sample_game(13, 61),
        sample_game(17, 88),
    ]
    opp = [sample_game(10, 40, opp_attempts=31, opp_yards=145) for _ in range(6)]

    p = project_player_rushing(
        player_name="Test Back",
        team_id=1,
        team_name="Test Team",
        own_matches=own,
        opp_matches=opp,
    )
    assert p is not None
    assert 10 < p.expected_attempts < 20
    assert p.expected_rushing_yards > 40
    assert p.reliability == "MEDIUM"


def test_count_half_line_fair() -> None:
    fair = count_fair_price(10.0, 8.5, "over", None)
    assert 0 < fair.win < 1
    assert fair.push == 0
    assert fair.fair_odds is not None


def test_normal_half_line_fair() -> None:
    fair = normal_fair_price(50.0, 15.0, 41.5, "over")
    assert fair.win > 0.5
    assert fair.fair_odds is not None

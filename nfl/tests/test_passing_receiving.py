from nfl.model.passing import project_player_passing
from nfl.model.receiving import project_player_receiving


def game(pass_attempts=34, pass_yards=245, player=None):
    return {
        "team": {
            "pass_attempts": pass_attempts,
            "team_net_passing_yards": pass_yards,
        },
        "opponent_team": {
            "pass_attempts": 36,
            "team_net_passing_yards": 255,
        },
        "players": [player] if player else [],
    }


def test_passing_projection() -> None:
    player = {
        "player_name": "Test QB",
        "passing": {
            "attempts": 33,
            "completions": 22,
            "yards": 250,
            "touchdowns": 2,
            "interceptions": 1,
        },
    }
    own = [game(player=player) for _ in range(8)]
    opp = [game(pass_attempts=35, player=player) for _ in range(8)]
    p = project_player_passing(
        player_name="Test QB",
        team_id=1,
        team_name="Test",
        own_matches=own,
        opp_matches=opp,
    )
    assert p is not None
    assert 25 < p.expected_attempts < 40
    assert 15 < p.expected_completions < 30
    assert p.expected_passing_yards > 150
    assert p.reliability == "MEDIUM"


def test_receiving_projection() -> None:
    player = {
        "player_name": "Test WR",
        "receiving": {
            "targets": 8,
            "receptions": 5,
            "yards": 70,
        },
    }
    own = [game(player=player) for _ in range(8)]
    opp = [game(player=player) for _ in range(8)]
    p = project_player_receiving(
        player_name="Test WR",
        team_id=1,
        team_name="Test",
        own_matches=own,
        opp_matches=opp,
    )
    assert p is not None
    assert p.expected_targets > 4
    assert p.expected_receptions > 2
    assert p.expected_receiving_yards > 25
    assert p.reliability == "MEDIUM"

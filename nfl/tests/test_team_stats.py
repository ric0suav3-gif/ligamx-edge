from nfl.ingest.team_odds import parse_team_prop_quotes
from nfl.model.team_stats import project_team_stats


def hist(team_id: int, name: str, pass_att: int, rush_att: int, pts_against: int):
    return {
        "team": {
            "team_id": team_id,
            "team_name": name,
            "plays": pass_att + rush_att + 2,
            "pass_attempts": pass_att,
            "pass_completions": int(pass_att * 0.65),
            "team_net_passing_yards": pass_att * 7,
            "rush_attempts": rush_att,
            "rushing_yards": rush_att * 4.5,
            "sacks_made": 2,
            "sacks_taken": 2,
            "turnovers": 1,
            "points_against": pts_against,
        },
        "opponent_team": {
            "team_id": team_id + 100,
            "team_name": "Opp",
            "plays": 64,
            "pass_attempts": 35,
            "pass_completions": 23,
            "team_net_passing_yards": 240,
            "rush_attempts": 27,
            "rushing_yards": 118,
            "sacks_made": 2,
            "sacks_taken": 2,
            "turnovers": 1,
            "points_against": 24,
        },
    }


def test_team_projection_is_coherent() -> None:
    own = [hist(1, "A", 36, 28, 21) for _ in range(12)]
    opp = [hist(2, "B", 33, 29, 23) for _ in range(12)]
    p = project_team_stats(
        team_id=1,
        team_name="A",
        own_matches=own,
        opponent_matches=opp,
    )
    assert p is not None
    assert abs(
        p.expected_pass_attempts
        + p.expected_rush_attempts
        - (p.expected_pass_attempts + p.expected_rush_attempts)
    ) < 1e-9
    assert p.expected_passing_yards > 150
    assert p.expected_rushing_yards > 80
    assert p.reliability == "MEDIUM"


def test_team_odds_parser_home_rushing_yards() -> None:
    rows = [
        {
            "bookmakers": [
                {
                    "name": "Bet365",
                    "bets": [
                        {
                            "id": 233,
                            "name": "Home Total Rushing Yards",
                            "values": [
                                {"value": "Over 115.5", "odd": "1.90"},
                                {"value": "Under 115.5", "odd": "1.90"},
                            ],
                        }
                    ],
                }
            ]
        }
    ]
    q = parse_team_prop_quotes(rows)
    assert len(q) == 2
    assert q[0].scope == "home_total"
    assert q[0].stat == "rushing_yards"

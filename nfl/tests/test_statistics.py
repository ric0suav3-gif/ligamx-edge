from nfl.ingest.statistics import (
    parse_passing,
    parse_player_groups,
    parse_receiving,
    parse_rushing,
    parse_team_statistics,
)


def stat_rows(mapping):
    return [{"name": k, "value": v} for k, v in mapping.items()]


def test_parse_passing() -> None:
    row = parse_passing(
        stat_rows(
            {
                "comp att": "29/42",
                "yards": "326",
                "average": "7.8",
                "passing touch downs": "2",
                "interceptions": "1",
                "sacks": "0-0",
                "rating": "82.5",
            }
        )
    )
    assert row["completions"] == 29
    assert row["attempts"] == 42
    assert row["yards"] == 326
    assert row["touchdowns"] == 2


def test_parse_receiving() -> None:
    row = parse_receiving(
        stat_rows(
            {
                "targets": "8",
                "total receptions": "5",
                "yards": "23",
                "average": "4.6",
                "longest reception": "10",
            }
        )
    )
    assert row["targets"] == 8
    assert row["receptions"] == 5
    assert row["yards"] == 23


def test_parse_rushing() -> None:
    row = parse_rushing(
        stat_rows(
            {
                "total rushes": "16",
                "yards": "101",
                "average": "6.3",
                "longest rush": "16",
            }
        )
    )
    assert row["attempts"] == 16
    assert row["yards"] == 101


def test_parse_team_statistics() -> None:
    rows = [
        {
            "team": {"id": 28, "name": "Denver Broncos"},
            "statistics": {
                "plays": {"total": 80},
                "yards": {"total": 512, "yards_per_play": "6.4"},
                "passing": {
                    "total": 326,
                    "comp_att": "29/42",
                    "interceptions_thrown": 1,
                },
                "rushings": {"total": 186, "attempts": 38},
                "turnovers": {"total": 1},
                "sacks": {"total": 3},
                "posession": {"total": "37:58"},
            },
        }
    ]
    row = parse_team_statistics(rows)[0]
    assert row["plays"] == 80
    assert row["pass_attempts"] == 42
    assert row["rush_attempts"] == 38
    assert row["team_net_passing_yards"] == 326

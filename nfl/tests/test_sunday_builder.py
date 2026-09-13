from nfl.scripts.build_sunday_ui import game_info, market_name


def test_game_info_reads_api_sports_shape():
    row = {
        "game": {"id": 99, "date": {"time": "13:00", "timezone": "America/New_York"}},
        "teams": {"away": {"name": "Away"}, "home": {"name": "Home"}},
    }

    assert game_info(row) == {
        "game_id": "99",
        "away": "Away",
        "home": "Home",
        "kickoff": "13:00",
        "timezone": "America/New_York",
    }


def test_market_name_is_human_readable():
    game = {"away": "Away", "home": "Home"}
    row = {"scope": "home_total", "stat": "points", "side": "over", "line": 24.5}

    assert market_name(row, game) == "Home · Puntos · Más 24.5"

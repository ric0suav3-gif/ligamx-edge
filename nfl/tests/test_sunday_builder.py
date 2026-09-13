from nfl.scripts.build_sunday_ui import build_payload, game_info, market_name


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


def test_build_payload_records_injury_screen(monkeypatch):
    monkeypatch.setattr("nfl.scripts.build_sunday_ui.load_json", lambda *_: None)

    payload = build_payload(
        "2026-09-13",
        [{"game": {"id": 99}, "teams": {"away": "Away", "home": "Home"}}],
        excluded_games={"99"},
        exclusion_note="Game omitted after injury review.",
    )

    assert payload["meta"]["exclusion_note"] == "Game omitted after injury review."

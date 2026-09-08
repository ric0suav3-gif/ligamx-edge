from ingest.statistics import parse_fixture_statistics


def test_missing_statistics_stay_missing() -> None:
    rows = [
        {
            "team": {"id": 1},
            "statistics": [
                {"type": "Total Shots", "value": None},
                {"type": "Corner Kicks", "value": 6},
            ],
        }
    ]
    parsed = parse_fixture_statistics(rows)
    assert parsed[1]["shots"] is None
    assert parsed[1]["corners"] == 6.0


def test_cards_combine_yellow_and_red() -> None:
    rows = [
        {
            "team": {"id": 1},
            "statistics": [
                {"type": "Yellow Cards", "value": 2},
                {"type": "Red Cards", "value": 1},
            ],
        }
    ]
    parsed = parse_fixture_statistics(rows)
    assert parsed[1]["cards"] == 3.0

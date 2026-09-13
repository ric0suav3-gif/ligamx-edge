from nfl.ingest.team_odds import parse_team_prop_quotes


def test_generic_home_away_and_match_totals_map_to_points() -> None:
    rows = [
        {
            "bookmakers": [
                {
                    "name": "Pinnacle",
                    "bets": [
                        {
                            "id": 3,
                            "name": "Over/Under",
                            "values": [
                                {"value": "Over 43.5", "odd": "1.91"},
                                {"value": "Under 43.5", "odd": "1.91"},
                            ],
                        },
                        {
                            "id": 8,
                            "name": "Total - Home",
                            "values": [
                                {"value": "Over 23.5", "odd": "1.90"},
                                {"value": "Under 23.5", "odd": "1.92"},
                            ],
                        },
                        {
                            "id": 9,
                            "name": "Total - Away",
                            "values": [
                                {"value": "Over 20.5", "odd": "1.95"},
                                {"value": "Under 20.5", "odd": "1.87"},
                            ],
                        },
                    ],
                }
            ]
        }
    ]

    quotes = parse_team_prop_quotes(rows)
    assert len(quotes) == 6
    assert {q.stat for q in quotes} == {"points"}
    scopes = {q.scope for q in quotes}
    assert scopes == {"match_total", "home_total", "away_total"}

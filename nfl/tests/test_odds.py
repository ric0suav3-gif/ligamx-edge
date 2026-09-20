from nfl.ingest.odds import best_player_prop_quotes, parse_player_prop_quotes


def test_parse_flat_rushing_props() -> None:
    rows = [
        {
            "bookmaker": "Bet365",
            "bet_id": 332,
            "name": "Player Rushing Attempts",
            "values": [
                {"value": "Sam Darnold - Over 2.5", "odd": "1.83"},
                {"value": "Sam Darnold - Under 2.5", "odd": "1.90"},
            ],
        },
        {
            "bookmaker": "Book B",
            "bet_id": 332,
            "name": "Player Rushing Attempts",
            "values": [
                {"value": "Sam Darnold - Over 2.5", "odd": "1.91"},
            ],
        },
    ]

    quotes = parse_player_prop_quotes(rows)
    assert len(quotes) == 3

    best = best_player_prop_quotes(quotes)
    over = [
        q for q in best
        if q.player_name == "Sam Darnold"
        and q.stat == "rush_attempts"
        and q.side == "over"
        and q.line == 2.5
    ][0]
    assert over.odd == 1.91
    assert over.bookmaker == "Book B"


def test_parse_nested_rushing_yards() -> None:
    rows = [
        {
            "bookmakers": [
                {
                    "name": "Bet365",
                    "bets": [
                        {
                            "id": 328,
                            "name": "Player Rushing Yards",
                            "values": [
                                {
                                    "value": "Drake Maye - Over 25.5",
                                    "odd": "1.90",
                                },
                                {
                                    "value": "Drake Maye - Under 25.5",
                                    "odd": "1.90",
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    ]

    quotes = parse_player_prop_quotes(rows)
    assert len(quotes) == 2
    assert {q.stat for q in quotes} == {"rushing_yards"}
    assert {q.line for q in quotes} == {25.5}

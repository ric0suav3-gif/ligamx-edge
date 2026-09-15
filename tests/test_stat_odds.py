from ingest.stat_odds import best_stat_quotes, parse_stat_quotes


def test_parse_stat_odds_and_best_price() -> None:
    rows = [
        {
            "bookmakers": [
                {
                    "name": "Book A",
                    "bets": [
                        {
                            "id": 57,
                            "name": "Home Corners Over/Under",
                            "values": [
                                {"value": "Over 5.5", "odd": "1.70"},
                                {"value": "Under 5.5", "odd": "2.00"},
                            ],
                        },
                        {
                            "id": 55,
                            "name": "Corners 1x2",
                            "values": [
                                {"value": "Home", "odd": "1.50"},
                                {"value": "Draw", "odd": "8.00"},
                                {"value": "Away", "odd": "3.20"},
                            ],
                        },
                    ],
                },
                {
                    "name": "Book B",
                    "bets": [
                        {
                            "id": 57,
                            "name": "Home Corners Over/Under",
                            "values": [
                                {"value": "Over 5.5", "odd": "1.80"},
                                {"value": "Under 5.5", "odd": "1.90"},
                            ],
                        }
                    ],
                },
            ]
        }
    ]

    quotes = parse_stat_quotes(rows)
    best = best_stat_quotes(quotes)

    over = [
        q for q in best
        if q.market_type == "home_total"
        and q.selection == "over"
        and q.line == 5.5
    ][0]
    assert over.odd == 1.80
    assert over.bookmaker == "Book B"

    h2h = [q for q in best if q.market_type == "h2h"]
    assert len(h2h) == 3

from ingest.odds import parse_1x2


def test_parse_1x2_selects_best_and_median() -> None:
    rows = [
        {
            "bookmakers": [
                {
                    "name": "Book A",
                    "bets": [
                        {
                            "name": "Match Winner",
                            "values": [
                                {"value": "Home", "odd": "2.00"},
                                {"value": "Draw", "odd": "3.50"},
                                {"value": "Away", "odd": "4.00"},
                            ],
                        }
                    ],
                },
                {
                    "name": "Book B",
                    "bets": [
                        {
                            "name": "Match Winner",
                            "values": [
                                {"value": "Home", "odd": "2.10"},
                                {"value": "Draw", "odd": "3.40"},
                                {"value": "Away", "odd": "3.90"},
                            ],
                        }
                    ],
                },
            ]
        }
    ]
    market = parse_1x2(rows)
    assert market is not None
    assert market.best["home"].odd == 2.10
    assert market.best["away"].odd == 4.00
    assert market.median_odds["draw"] == 3.45

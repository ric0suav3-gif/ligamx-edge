from __future__ import annotations

UCL_LEAGUE_ID = 2
SEASON = 2026
MATCH_DATE = "2026-09-08"

FIXTURES = {
    1635643: {
        "home": {"id": 569, "name": "Club Brugge KV"},
        "away": {"id": 66, "name": "Aston Villa"},
    },
    1635609: {
        "home": {"id": 575, "name": "AEK Athens FC"},
        "away": {"id": 1026, "name": "Lask Linz"},
    },
    1635683: {
        "home": {"id": 79, "name": "Lille"},
        "away": {"id": 543, "name": "Real Betis"},
    },
    1635652: {
        "home": {"id": 165, "name": "Borussia Dortmund"},
        "away": {"id": 533, "name": "Villarreal"},
    },
    1635654: {
        "home": {"id": 212, "name": "FC Porto"},
        "away": {"id": 50, "name": "Manchester City"},
    },
    1635714: {
        "home": {"id": 541, "name": "Real Madrid"},
        "away": {"id": 505, "name": "Inter"},
    },
}

TEAMS = {
    team["id"]: team["name"]
    for fixture in FIXTURES.values()
    for team in (fixture["home"], fixture["away"])
}

# Verified from API-Football for season 2026.
DOMESTIC_LEAGUES = {
    575: {"league_id": 197, "league_name": "Super League 1", "country": "Greece"},
    66: {"league_id": 39, "league_name": "Premier League", "country": "England"},
    165: {"league_id": 78, "league_name": "Bundesliga", "country": "Germany"},
    569: {"league_id": 144, "league_name": "Jupiler Pro League", "country": "Belgium"},
    212: {"league_id": 94, "league_name": "Primeira Liga", "country": "Portugal"},
    505: {"league_id": 135, "league_name": "Serie A", "country": "Italy"},
    1026: {"league_id": 218, "league_name": "Bundesliga", "country": "Austria"},
    79: {"league_id": 61, "league_name": "Ligue 1", "country": "France"},
    50: {"league_id": 39, "league_name": "Premier League", "country": "England"},
    543: {"league_id": 140, "league_name": "La Liga", "country": "Spain"},
    541: {"league_id": 140, "league_name": "La Liga", "country": "Spain"},
    533: {"league_id": 140, "league_name": "La Liga", "country": "Spain"},
}

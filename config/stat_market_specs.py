from __future__ import annotations

# User-priority markets for UCL Edge.
# Dispersion parameters will be estimated from historical data rather than
# hard-coded here.
STAT_MARKETS = {
    "shots": {
        "label": "Shots",
        "family": "negative_binomial",
        "team_totals": True,
        "match_totals": True,
        "h2h": True,
        "asian_handicap": True,
        "priority": 1,
    },
    "shots_on_target": {
        "label": "Shots on Target",
        "family": "negative_binomial",
        "team_totals": True,
        "match_totals": True,
        "h2h": True,
        "asian_handicap": True,
        "priority": 2,
    },
    "corners": {
        "label": "Corners",
        "family": "negative_binomial",
        "team_totals": True,
        "match_totals": True,
        "h2h": True,
        "asian_handicap": True,
        "priority": 3,
    },
    "fouls": {
        "label": "Fouls",
        "family": "negative_binomial",
        "team_totals": True,
        "match_totals": True,
        "h2h": True,
        "asian_handicap": True,
        "priority": 4,
    },
    "offsides": {
        "label": "Offsides",
        "family": "negative_binomial",
        "team_totals": True,
        "match_totals": True,
        "h2h": True,
        "asian_handicap": True,
        "priority": 5,
    },
    "cards": {
        "label": "Cards",
        "family": "negative_binomial",
        "team_totals": True,
        "match_totals": True,
        "h2h": True,
        "asian_handicap": True,
        "priority": 6,
        "context": ["referee"],
    },
    "goals": {
        "label": "Goals",
        "family": "poisson",
        "team_totals": True,
        "match_totals": True,
        "h2h": False,
        "asian_handicap": True,
        "priority": 7,
    },
}

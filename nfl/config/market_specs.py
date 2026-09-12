from __future__ import annotations

MARKET_SPECS = {
    "pass_attempts": {
        "priority": 1,
        "entity": "player",
        "families": ("poisson", "negative_binomial"),
        "markets": ("player_total", "h2h"),
    },
    "completions": {
        "priority": 2,
        "entity": "player",
        "families": ("binomial_conditional", "beta_binomial"),
        "markets": ("player_total", "h2h"),
    },
    "passing_yards": {
        "priority": 3,
        "entity": "player",
        "families": ("normal", "student_t", "compound_opportunity"),
        "markets": ("player_total", "h2h"),
    },
    "rush_attempts": {
        "priority": 4,
        "entity": "player",
        "families": ("poisson", "negative_binomial"),
        "markets": ("player_total", "h2h"),
    },
    "rushing_yards": {
        "priority": 5,
        "entity": "player",
        "families": ("normal", "student_t", "compound_opportunity"),
        "markets": ("player_total", "h2h"),
    },
    "targets": {
        "priority": 6,
        "entity": "player",
        "families": ("poisson", "negative_binomial"),
        "markets": ("player_total", "h2h"),
    },
    "receptions": {
        "priority": 7,
        "entity": "player",
        "families": ("binomial_conditional", "beta_binomial"),
        "markets": ("player_total", "h2h"),
    },
    "receiving_yards": {
        "priority": 8,
        "entity": "player",
        "families": ("normal", "student_t", "compound_opportunity"),
        "markets": ("player_total", "h2h"),
    },
    "sacks": {
        "priority": 9,
        "entity": "team",
        "families": ("poisson", "negative_binomial"),
        "markets": ("team_total", "match_total", "h2h"),
    },
    "interceptions": {
        "priority": 10,
        "entity": "player",
        "families": ("poisson", "bernoulli_mixture"),
        "markets": ("player_total",),
    },
    "passing_touchdowns": {
        "priority": 11,
        "entity": "player",
        "families": ("poisson", "negative_binomial"),
        "markets": ("player_total",),
    },
    "points": {
        "priority": 12,
        "entity": "team",
        "families": ("empirical", "compound_score"),
        "markets": ("team_total", "match_total", "asian_handicap"),
    },
}

# Phase 2 / tail-sensitive markets: longest rush, longest reception,
# anytime TD, first TD and similar event markets. These should not be enabled
# until the core opportunity/efficiency model is walk-forward calibrated.

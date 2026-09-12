from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EloRatings:
    ratings: dict[int, float] = field(default_factory=dict)
    initial: float = 1500.0
    k: float = 20.0
    home_advantage: float = 55.0

    def get(self, team_id: int) -> float:
        return self.ratings.get(team_id, self.initial)

    def expected_home(self, home_id: int, away_id: int) -> float:
        diff = (
            self.get(home_id)
            + self.home_advantage
            - self.get(away_id)
        )
        return 1.0 / (1.0 + 10 ** (-diff / 400.0))

    def update(
        self,
        home_id: int,
        away_id: int,
        home_goals: int,
        away_goals: int,
    ) -> None:
        expected = self.expected_home(home_id, away_id)
        if home_goals > away_goals:
            actual = 1.0
        elif home_goals == away_goals:
            actual = 0.5
        else:
            actual = 0.0

        margin = abs(home_goals - away_goals)
        margin_mult = 1.0 if margin <= 1 else min(1.75, 1.0 + 0.15 * (margin - 1))
        delta = self.k * margin_mult * (actual - expected)

        self.ratings[home_id] = self.get(home_id) + delta
        self.ratings[away_id] = self.get(away_id) - delta

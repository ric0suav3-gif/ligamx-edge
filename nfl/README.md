# NFL Edge v1

NFL betting model focused on statistical markets rather than moneyline-first picks.

## Primary target markets

1. Player passing: attempts, completions, passing yards, passing TDs, interceptions.
2. Player rushing: attempts, rushing yards, longest rush (later).
3. Player receiving: targets, receptions, receiving yards, longest reception (later).
4. Team totals: plays, pass attempts, rush attempts, passing/rushing yards, sacks, turnovers, points.
5. H2H player/team stat markets where settlement rules are explicit.
6. Game/team Asian-style totals and alternate lines where the sportsbook offers them.

## Data required before modeling

The provider should expose, ideally with historical access:

- schedules and game IDs
- box scores and player game logs
- play-by-play
- rosters and stable player/team IDs
- depth charts
- injury/practice reports and inactive status
- snap counts / participation if available
- starting QB and starter information
- weather and venue (or enough fields to join an external weather source)
- betting odds and player props, or enough identifiers to join a separate odds provider

Historical point-in-time injuries/depth charts are highly desirable. If the provider only exposes current-state injury/depth-chart data, we must not pretend those fields existed historically during backtests.

## Modeling architecture

Pregame projection is decomposed into:

team pace / expected plays
→ pass-rate and rush-rate expectation
→ offensive line / pressure / sack environment
→ opponent defensive adjustment
→ player opportunity share (snaps, routes, targets, carries)
→ efficiency per opportunity
→ weather / venue / injuries / game context
→ player and team count/yards distributions
→ fair lines / fair odds
→ bookmaker comparison
→ walk-forward calibration

The first release should prioritize markets with transparent volume mechanics: attempts, completions, receptions, carries, passing/rushing/receiving yards. Touchdowns, longest-play markets and anytime TDs come later because their tails are harder to calibrate.

## Validation rule

No current sportsbook disagreement is called a validated edge until the market has passed leakage-free walk-forward testing. Historical features must only use information that was available before kickoff.

## Secrets

Never commit an NFL API key. Keep provider credentials in local environment variables / .env only.

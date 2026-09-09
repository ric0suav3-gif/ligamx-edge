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


## API-Sports NFL setup

The provider client is now implemented under `nfl/ingest/api_sports.py`.

From the repository root:

```bash
git checkout nfl-edge-v1
git pull
python -m pip install -r nfl/requirements.txt
cp .env.example .env
```

Put your purchased API-Sports key in the local `.env` file:

```env
NFL_API_KEY=YOUR_KEY_HERE
NFL_API_BASE_URL=https://v1.american-football.api-sports.io
```

Do **not** commit `.env` and do not put the API key in the iPhone/HTML interface.

### First connection test

```bash
python nfl/scripts/test_api.py
```

This checks NFL league id 1, season 2026 and prints the provider coverage flags.

### Audit the betting catalogue

Run this before we write a sportsbook parser:

```bash
python nfl/scripts/audit_odds_bets.py
```

It saves the full `/odds/bets` catalogue and highlights stat/prop-like market names. We will map exact bet IDs only after seeing the real catalogue; no guessed bet IDs.

### Audit a current slate

```bash
python nfl/scripts/audit_day.py --date 2026-09-09
```

The raw slate is cached under `nfl/data/cache/audits/`.

### Audit a completed NFL game

API-Sports' current official guide uses completed 2025 NFL game id `17377` as its example, which makes it convenient for inspecting response structure:

```bash
python nfl/scripts/audit_game.py --game 17377
```

For smaller group-specific output:

```bash
python nfl/scripts/audit_game.py --game 17377 --group passing
python nfl/scripts/audit_game.py --game 17377 --group receiving
python nfl/scripts/audit_game.py --game 17377 --group rushing
```

The next implementation step is driven by these real responses:

1. normalize player-game passing/rushing/receiving fields;
2. backfill leakage-free player game logs;
3. build team pace/pass-rate/rush-rate environments;
4. project player opportunities;
5. fit prop distributions;
6. parse exact API-Sports player-prop bet IDs;
7. compare model fair prices with bookmaker consensus;
8. walk-forward calibrate before labeling any disagreement a validated edge.

### Important provider limitations

API-Sports documents injuries as current-state data without historical injury archives and pre-match odds with only short history. From day one, NFL Edge should snapshot current injuries and odds locally so future backtests can use information that actually existed before kickoff.

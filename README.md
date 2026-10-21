# Liga MX Edge V33

The [dashboard](index.html) projects Liga MX goals, shots, shots on target, corners, fouls, cards and offsides. Fixtures and completed-match statistics come from ESPN's public soccer feed; **no API-Football key is required**. Model prices are fair-price estimates, not sportsbook quotes or guaranteed edges. Check the exact line and price at your book before betting.

## What changed in V33 (October 20)

- **18 more matches** (J11–J12, Oct 9–18) merged: 58 Apertura games on top of the v30 prior, data through Oct 18.
- **Out-of-sample check of the V32 tuning:** on the 18 new games, EWMA α=0.15 again beat 0.0539 for goals, shots on target, corners, fouls and offsides. Offsides now uses 0.15; cards stay slow.
- **Season bias correction:** this Apertura is running hotter than the prior (shots +7.5%, SOT +11.6%, corners +9.1%, fouls −5.1% vs projection). A shrunk correction (20-game prior) improved walk-forward log loss for shots, SOT, corners and fouls, so it is applied to those four only (`meta.season_bias`).
- **Liguilla stakes** (`scripts/liguilla_stakes.py`): top 8 qualify directly, no play-in. 20,000 simulations of the remaining fixtures give each team's top-8 probability and how much its next result moves it. That leverage shifts goal expectations by up to ±6%. The 6% is a prior, not fitted.
- **Polymarket 1X2:** the page reads Polymarket's Liga MX match markets live (Gamma API, no key) and blends them with the model: 70% market when liquidity ≥ $50k, else 50%. The blended 1X2 is what the "Valor vs casa" section compares against book odds.
- **Public betting %:** not available for Liga MX. Polymarket doesn't publish it and Action Network's public-betting feed doesn't carry Liga MX.

## Refresh the model

From the repository root, on a machine that can reach ESPN:

```powershell
python scripts/sync_ligamx_espn.py
python scripts/edge_card.py --from 2026-10-24 --to 2026-10-26
```

If ESPN is blocked (as in Claude's cloud sandbox), export the feed from a browser into the same JSON shape as `data/espn_browser_2026-10-20.json` and run:

```powershell
python scripts/sync_ligamx_espn.py --offline data/espn_browser_YYYY-MM-DD.json
```

The collector replays every completed game after the immutable [v30 base](data/ligamx_base_v30.json), so re-running it cannot count a game twice. It updates `index.html` and `ligamx edge.html`, writes [the snapshot](data/ligamx_espn_latest.json) (matches, standings, remaining fixtures, stakes) and re-runs the liguilla simulation. The page's **Actualizar ESPN** button still does no-key incremental updates on the device.

`scripts/edge_card.py` writes `tracking/edge-card-<date>.md`: model vs Polymarket vs blended 1X2, stakes, and fair prices for goals, shots, SOT, corners, fouls, cards and offsides. Polymarket prices come from the newest `data/polymarket_*.json`.

```powershell
python scripts/calibrate_ewma.py
python -m pytest -q tests
```

Model prices are fair-price estimates, not sportsbook quotes or guaranteed edges. Check the exact line and price at your book before betting.

The older [Today Edge](today-edge.html) is a separate UEFA card that still uses API-Football. Its builder has not been migrated by this Liga MX update.

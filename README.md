# Liga MX Edge V32

The [dashboard](index.html) projects Liga MX goals, shots, shots on target, corners, fouls, cards and offsides. Fixtures and completed-match statistics come from ESPN's public soccer feed; **no API-Football key is required**. Model prices are fair-price estimates, not sportsbook quotes or guaranteed edges. Check the exact line and price at your book before betting.

## Refresh the model

From the repository root:

```powershell
python scripts/sync_ligamx_espn.py
python scripts/preview_ligamx.py
```

The collector replays completed games after the immutable [v30 base](data/ligamx_base_v30.json), updates `index.html` and `ligamx edge.html`, and saves [the source snapshot and grades](data/ligamx_espn_latest.json). Re-running it cannot count a game twice. The page also has a no-key **Actualizar ESPN** button for future incremental updates on the current device.

For the October 9 build, 40 completed matches after August 28 were merged through September 27. The saved September 12–13 card graded 8 wins and 5 losses. A 40-game chronological replay favored EWMA α=0.15 over the old 0.0539 for goals, shots, shots on target, corners and fouls; cards and offsides retain the slower update. This is a small retrospective tuning sample, not proof of future profitability. The model's historical league baselines were not re-estimated.

```powershell
python scripts/calibrate_ewma.py
python scripts/calibrate_goal_form.py
```

The separate current-season goals-form overlay did **not** improve holdout goal log loss, so it was not applied. Referee foul effects remain shrunk to 50% after both tracked foul overs lost.

The older [Today Edge](today-edge.html) is a separate UEFA card that still uses API-Football. Its builder has not been migrated by this Liga MX update.

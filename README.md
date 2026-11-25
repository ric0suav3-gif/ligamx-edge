
# Liga MX Edge V34 / UCL Edge V3 (November 25)

- **Auto-update.** `.github/workflows/update-data.yml` runs at 07:10, 10:40, 12:50 and 17:10 Mexico City time (and on demand from the Actions tab → update-data → Run workflow). It replays new Liga MX games from ESPN (`scripts/sync_ligamx_espn.py`), rebuilds the UCL model for the next 7 days (`node ucl/build_node.js` → `data/ucl_latest.json` → `ucl.html`), commits and asks GitHub Pages to publish. No keys needed.
- **Playdoit tab** (first tab on both pages). `playdoit.js` reads Playdoit's live lines from the phone (Altenar widget API, public): team and match shots, shots on target, corners, offsides, cards, goals, 1X2, 1UP (Súper Pago Anticipado) and BTTS. Each line shows Playdoit's price, the probability and EV. The probability is 50% model + 50% Playdoit's no-vig price, because raw model edges on props were far too big. A market where the model is 20+ points away from Playdoit's main line is flagged and kept out of the value list. GitHub's servers are blocked by Playdoit (403), so lines are only fetched on the phone.
- **UCL V3 model.** Season calibration from the test set (actual/predicted, shrunk with 40 games: shots ×1.02, SOT ×0.98, corners ×0.96, offsides ×1.17), then 30% toward this season's UCL averages ((team for + opponent against)/2). If ESPN has no odds, match strength comes from Playdoit's 1X2 and goal line. The Playdoit tab has a manual "Bajas de ataque" setting per team and lists API-Football injuries when the key is saved on the phone.
- **Liga MX goals in the Playdoit tab** come from Playdoit's own 1X2 + total (the Liga MX goal model runs far from the market in liguilla). A model saved on the phone is now used only if it has newer data than the page.
- When `playdoit.js` changes, bump the `?v=` on its `<script>` tag in `index.html` and `web/ucl_template.html` so phones don't keep the old copy.

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

## UCL Edge V2 (October 21)

[`ucl.html`](ucl.html) is the Champions League page, built the same way as Liga MX Edge but with no API key:

- **Match strength from the market.** DraftKings 1X2 + total (from ESPN) blended 50/50 with Polymarket, converted to expected goals.
- **Team style from domestic leagues.** Opponent-adjusted attack/defence ratings per stat from 15 ESPN leagues. The part explained by team strength is removed, and what is left (e.g. "Villa concede more cards than their level") carries into the UCL.
- **UCL layer.** Poisson regression per stat on UCL games since Aug 2025 that have odds (supremacy, tempo, style), negative-binomial dispersion.
- **Backtest** on the 45 games of the 2026-27 league phase: market + style beat market-only for every stat, mostly for shots and shots on target. Offsides have no domestic feed.
- The page refreshes DraftKings and Polymarket prices live before kickoff. Public betting % (Action Network) is a snapshot from build time.

Rebuild on match day (the fetches run in a browser, because ESPN is blocked from Claude's sandbox):

```js
// in a browser tab on site.api.espn.com
eval(await (await fetch('https://raw.githubusercontent.com/ric0suav3-gif/ligamx-edge/main/ucl/model.js')).text());
const M = await UCLM.build({today: '2026-10-28'});
```

Save the export as `data/ucl_model_<date>.json`, then:

```powershell
python ucl/build_page.py data/ucl_model_<date>.json
node ucl/card.js data/ucl_model_<date>.json > tracking/ucl-edge-card-<date>.md
```

The September API-Football UCL page is kept in [`archive/`](archive/ucl-edge-2026-09-10.html). The older [Today Edge](today-edge.html) still uses API-Football.

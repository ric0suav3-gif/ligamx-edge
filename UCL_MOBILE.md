# UCL Edge Mobile

The UCL iPhone UI is intentionally modeled after LigaMX Edge v29:

- fixture selector
- Totales / Por equipo / H2H / AH / Picks tabs
- adjustable market lines
- fair odds and model probabilities
- API-Football median/best bookmaker snapshot when the exact line exists
- LOW / proxy warnings instead of silently replacing missing data with zero
- local iPhone pick register
- optional official tracker summary from `tracking/ucl_results.json`

## Refresh after the UCL API pipeline has run

```bash
python scripts/refresh_ucl_mobile.py
```

This reads the current `config/ucl_2026.py` slate and local `data/cache/` model/odds files and writes:

```text
UCL_Edge_iPhone.html
```

No API key or `.env` value is embedded in the HTML. The page contains only the generated model snapshot and bookmaker data already returned by API-Football.

## Publish to GitHub Pages

Commit the generated HTML to `ucl-edge-v1`:

```bash
git add UCL_Edge_iPhone.html
git commit -m "Refresh UCL Edge mobile"
git push
```

`.github/workflows/ucl-pages.yml` deploys that generated file as the GitHub Pages `index.html`.

## Important

Bookmaker prices are a build-time snapshot. Run `scripts/audit_odds_markets.py` and then `scripts/refresh_ucl_mobile.py` again whenever you want fresh prices on the mobile UI.

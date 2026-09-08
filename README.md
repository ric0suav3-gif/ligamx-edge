# ligamx-edge

Original Liga MX / Leagues Cup betting model plus an in-progress UEFA Champions League research branch.

## UCL Edge v1

The first UCL implementation lives in Python and keeps API credentials out of source control.

### Setup

1. Copy `.env.example` to `.env`.
2. Put your API-Football key in `API_FOOTBALL_KEY`.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Smoke-test API-Football for the 2026-09-08 Champions League slate:

```bash
python scripts/test_api.py --date 2026-09-08 --season 2026
python scripts/audit_ucl_day.py --date 2026-09-08 --season 2026
```

The API layer currently supports league coverage, fixtures, fixture statistics,
lineups, injuries, and odds. Missing statistics are preserved as `None` rather
than being silently converted to zero.

### Model components

- Exponentially weighted form (`model/ewma.py`)
- Poisson / negative-binomial count distributions (`model/distributions.py`)
- European Elo scaffold (`model/elo.py`)
- Cross-league normalization (`model/league_strength.py`)
- UCL goal / 1X2 projection scaffold (`model/ucl.py`)

The UCL model is intentionally separate from the working HTML app until the
historical ingestion and walk-forward calibration are validated.

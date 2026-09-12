# ligamx-edge

Original Liga MX / Leagues Cup betting model plus an in-progress UEFA Champions League research branch.

## UCL Edge

The UCL branch is being rebuilt around the markets this model is actually meant to attack:

- Shots
- Shots on Target
- Corners
- Fouls
- Offsides
- Cards
- Goals
- Team Totals
- H2H count markets
- Asian handicaps / Asian totals

Moneyline / 1X2 remains only as a background diagnostic.

## Setup

1. Copy `.env.example` to `.env`.
2. Put your API-Football key in `API_FOOTBALL_KEY`.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

The API client throttles requests, retries 429s, and caches successful calls under
`data/cache/` so interrupted backfills can be resumed safely.

## Existing domestic team profiles

```bash
python scripts/backfill_domestic_history.py --matches 30
python scripts/build_team_profiles.py
```

## Stat-market pipeline

### 1. Build league + UCL stat environments

This estimates home/away means and Poisson / negative-binomial dispersion for
shots, SOT, corners, fouls, cards and offsides.

```bash
python scripts/build_stat_baselines.py
```

### 2. Backfill each club's proper-stage UCL stat history

```bash
python scripts/backfill_ucl_team_history.py --matches 20
```

### 3. Estimate stat-specific domestic-to-UCL transfer factors

Instead of applying one generic league-strength multiplier to every market,
this learns separate shrunk transfer factors for shots, SOT, corners, fouls,
cards and offsides from each club's actual UCL history.

```bash
python scripts/build_stat_transfers.py
```

Clubs with little or no proper-stage UCL sample automatically shrink back to a
neutral factor of 1.00.

### 4. Price the first stat markets

```bash
python scripts/predict_stat_markets.py
```

The first output focuses on:

- Shots
- Shots on Target
- Corners
- Team totals
- H2H
- Asian handicaps

The script produces expected counts, fair H2H prices, fair over/under prices
around the projected team total, and fair Asian handicap prices.

## Modeling components

- EWMA recency weighting: `model/ewma.py`
- Poisson / negative-binomial count distributions: `model/distributions.py`
- Dispersion fitting: `model/dispersion.py`
- Team-vs-opponent stat projection: `model/stat_projection.py`
- Team totals / H2H / Asian settlement math: `model/stat_markets.py`
- UCL stat transfer estimation: `scripts/build_stat_transfers.py`

## Important

Current outputs are diagnostic fair prices, not validated betting signals.
Before ranking actual edges, the next major milestone is walk-forward
backtesting plus bookmaker line ingestion for stat markets.

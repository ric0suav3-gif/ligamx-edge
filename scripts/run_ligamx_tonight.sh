#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

TARGET_DATE="${1:-$(TZ=America/Mexico_City date +%F)}"
SEASON="${2:-2026}"

echo "Liga MX API-Football collection"
echo "Date: $TARGET_DATE | season: $SEASON"
echo

echo "Checking Python dependencies..."
if ! python - <<'PY'
import requests
import dotenv
PY
then
  echo "Installing repo Python dependencies..."
  python -m pip install -r requirements.txt
fi

echo
echo "Preserving the complete embedded V29 historical model first..."
python scripts/snapshot_ligamx_prior.py

echo
echo "Collecting tonight's Liga MX data from API-Football..."
python scripts/collect_ligamx_tonight.py \
  --date "$TARGET_DATE" \
  --season "$SEASON" \
  --matches 30 \
  --league-window 120

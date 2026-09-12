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
echo "Checking API-Football credentials..."
if ! python - <<'PY'
import os
from pathlib import Path
from dotenv import load_dotenv
env_path = Path.cwd() / ".env"
load_dotenv(dotenv_path=env_path, override=False)
raise SystemExit(0 if os.getenv("API_FOOTBALL_KEY") else 1)
PY
then
  echo
  echo "API_FOOTBALL_KEY is not available in this Codespace."
  echo "Set it locally without exposing it in chat or shell history:"
  echo "  bash scripts/setup_api_football_env.sh"
  echo
  echo "Then rerun:"
  echo "  bash scripts/run_ligamx_tonight.sh $TARGET_DATE $SEASON"
  exit 2
fi

echo
echo "Collecting tonight's Liga MX data from API-Football..."
python scripts/collect_ligamx_tonight.py \
  --date "$TARGET_DATE" \
  --season "$SEASON" \
  --matches 30 \
  --league-window 120

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

DATE="${1:-$(TZ=America/Mexico_City date +%F)}"
SEASON="${2:-2026}"

python -m pip install -r requirements.txt >/dev/null

if [[ ! -f .env ]]; then
  echo "Missing .env. Run: bash scripts/setup_api_football_env.sh"
  exit 2
fi

python -u scripts/refresh_ligamx_v30_data.py \
  --date "$DATE" \
  --season "$SEASON" \
  --ref-seasons "$SEASON" "$((SEASON-1))"

echo
echo "Generated: exports/LigaMX_Edge_V30.html"

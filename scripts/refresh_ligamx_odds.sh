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

echo "Refreshing API-Football sportsbook odds..."
python -u scripts/refresh_ligamx_odds.py --date "$DATE" --season "$SEASON"

echo
echo "Refreshing derby referee + H2H discipline context..."
python -u scripts/refresh_ligamx_derby_context.py \
  --date "$DATE" \
  --season "$SEASON" \
  --h2h-last 10

echo
echo "Updated:"
echo "  ligamx edge.html"
echo "  exports/LigaMX_Edge_V30.html"
echo
echo "Audit JSON:"
echo "  exports/ligamx_odds_${DATE//-/_}.json"
echo "  exports/ligamx_derby_context_${DATE//-/_}.json"

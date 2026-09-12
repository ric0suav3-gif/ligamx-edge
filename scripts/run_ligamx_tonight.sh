#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

TARGET_DATE="${1:-$(TZ=America/Mexico_City date +%F)}"
SEASON="${2:-2026}"

echo "Liga MX API-Football collection"
echo "Date: $TARGET_DATE | season: $SEASON"
echo

python scripts/collect_ligamx_tonight.py \
  --date "$TARGET_DATE" \
  --season "$SEASON" \
  --matches 30 \
  --league-window 120

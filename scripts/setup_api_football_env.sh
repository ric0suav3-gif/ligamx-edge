#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ -n "${API_FOOTBALL_KEY:-}" ]]; then
  echo "API_FOOTBALL_KEY is already available in this shell."
  exit 0
fi

if [[ -f .env ]] && grep -Eq '^API_FOOTBALL_KEY=.+$' .env; then
  echo ".env already contains API_FOOTBALL_KEY."
  exit 0
fi

echo "This stores the API-Football key only in local .env (gitignored)."
read -r -s -p "Paste API-Football key (input hidden): " KEY
echo

if [[ -z "$KEY" ]]; then
  echo "No key entered; nothing changed."
  exit 1
fi

cat > .env <<EOF
API_FOOTBALL_KEY=$KEY
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io
API_FOOTBALL_MIN_INTERVAL=0.40
API_FOOTBALL_MAX_RETRIES=6
EOF
unset KEY

echo "Saved local .env. It is ignored by git and will not be committed."

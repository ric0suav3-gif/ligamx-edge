#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SRC="$ROOT/UCL_Edge_iPhone.html"
TARGET_NAME="ucl edge.html"

cd "$ROOT"

echo "Rebuilding self-contained UCL Edge HTML from local API-Football caches..."
python scripts/refresh_ucl_mobile.py

if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC after rebuild."
  exit 1
fi

if grep -q '__UCL_DATA__' "$SRC"; then
  echo "Refusing to publish: UI still contains the unreplaced data placeholder."
  exit 1
fi

# Guard against accidentally publishing secret names/headers. The generated page
# should contain only model outputs and cached public market data.
if grep -Eq 'API_FOOTBALL_KEY|x-apisports-key|RAPIDAPI_KEY|NFL_API_KEY' "$SRC"; then
  echo "Refusing to publish: possible secret/key name found in generated HTML."
  exit 1
fi

echo "Publishing to main exactly like the existing Liga MX static model..."
git fetch origin main

TMP="$(mktemp -d)"
cleanup() {
  git worktree remove --force "$TMP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

git worktree add --detach "$TMP" origin/main >/dev/null
cp "$SRC" "$TMP/$TARGET_NAME"

cd "$TMP"
git add "$TARGET_NAME"
if git diff --cached --quiet; then
  echo "Static UCL page is already current on main."
else
  git commit -m "Refresh UCL Edge mobile static model" >/dev/null
  git push origin HEAD:main
fi

echo
echo "Published as a normal static HTML file on main."
echo "URL: https://ric0suav3-gif.github.io/ligamx-edge/ucl%20edge.html"
echo "No separate UCL Pages workflow is used."

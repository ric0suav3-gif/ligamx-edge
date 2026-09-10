#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SRC="$ROOT/UCL_Edge_iPhone.html"
TARGET_NAME="ucl edge.html"

if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC"
  echo "Run: python scripts/refresh_ucl_mobile.py"
  exit 1
fi

if grep -q '__UCL_DATA__' "$SRC"; then
  echo "Refusing to publish: UI still contains the unreplaced data placeholder."
  exit 1
fi

if grep -Eq 'API_FOOTBALL_KEY|x-apisports-key|RAPIDAPI_KEY|NFL_API_KEY' "$SRC"; then
  echo "Refusing to publish: possible secret/key name found in generated HTML."
  exit 1
fi

cd "$ROOT"
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
  echo "No static UCL page changes to publish."
  exit 0
fi

git commit -m "Refresh UCL Edge mobile static model" >/dev/null
git push origin HEAD:main

echo
echo "Published like Liga MX: a self-contained HTML file on main."
echo "URL: https://ric0suav3-gif.github.io/ligamx-edge/ucl%20edge.html"
echo "The existing main Pages deployment will serve it; there is no separate UCL workflow."

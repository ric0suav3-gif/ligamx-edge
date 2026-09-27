#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

DATE="${1:-$(TZ=America/New_York date +%F)}"
export DATE_FOR_NFL="$DATE"
SEASON="${2:-2026}"

if [[ ! -f .env ]]; then
  echo "Missing .env with NFL_API_KEY. Keep the key local; do not commit it."
  exit 2
fi

python -m pip install -r nfl/requirements.txt >/dev/null

echo "1/6 Grade the currently embedded prior Sunday card with API-Sports..."
python -u nfl/scripts/grade_sunday_card.py || true

echo
echo "2/6 Pull today's NFL slate from API-Sports..."
python -u nfl/scripts/audit_day.py --date "$DATE" --season "$SEASON"

echo
echo "3/6 Snapshot current injuries from API-Sports..."
python -u nfl/scripts/audit_sunday_injuries.py --date "$DATE"

GAME_IDS=$(python - <<'PY'
import json
from pathlib import Path
p=Path("nfl/data/cache/audits") / ("slate_" + __import__("os").environ["DATE_FOR_NFL"] + ".json")
rows=json.loads(p.read_text())
ids=[]
for row in rows:
    game=row.get("game") or row
    gid=row.get("id") or game.get("id")
    if gid is not None: ids.append(str(gid))
print(" ".join(ids))
PY
)

echo
echo "4/6 Build leakage-safe contexts and projections..."
for G in $GAME_IDS; do
  echo "=== game $G ==="
  python -u nfl/scripts/backfill_game_context.py --game "$G" --matches 20 --seasons "$SEASON" "$((SEASON-1))" "$((SEASON-2))"
  python -u nfl/scripts/predict_team_stats.py --game "$G"
  python -u nfl/scripts/compare_team_edges.py --game "$G" --min-books 2 --min-ev 0
done

echo
echo "5/6 Build Sunday mobile card..."
python -u nfl/scripts/build_sunday_ui.py --date "$DATE"

echo
echo "6/6 Export inspectable API/model snapshot..."
python -u nfl/scripts/export_sunday_payload.py --date "$DATE"

echo
echo "READY"
echo "  NFL_Edge_iPhone.html"
echo "  exports/nfl_sunday_${DATE//-/_}_api.json"
echo "  exports/nfl_injuries_${DATE//-/_}_api.json"
echo "  exports/nfl_grade_*_api.json"

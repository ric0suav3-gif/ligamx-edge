from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient
from nfl.ingest.cache import load_json


def main() -> None:
    ap = argparse.ArgumentParser(description="Snapshot current NFL injuries for every team on a cached Sunday slate.")
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    slate = load_json("audits", f"slate_{args.date}")
    if not slate:
        raise SystemExit("Missing slate cache; run audit_day.py first.")

    teams: dict[int, str] = {}
    games = []
    for row in slate:
        teams_obj = row.get("teams") or {}
        game = row.get("game") or row
        gid = str(row.get("id") or game.get("id"))
        item = {"game_id": gid, "teams": {}}
        for side in ("away", "home"):
            t = teams_obj.get(side) or {}
            tid = int(t["id"])
            name = str(t.get("name") or tid)
            teams[tid] = name
            item["teams"][side] = {"id": tid, "name": name}
        games.append(item)

    client = APINFLClient()
    by_team = {}
    for i,(tid,name) in enumerate(sorted(teams.items(), key=lambda x:x[1]),1):
        rows = client.injuries(team=tid).response
        by_team[str(tid)] = {"team": name, "injuries": rows}
        print(f"injuries {i}/{len(teams)} | {name}: {len(rows)}")

    payload = {"source":"API-Sports American Football","date":args.date,"games":games,"teams":by_team}
    out = ROOT / "exports" / f"nfl_injuries_{args.date.replace('-', '_')}_api.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()

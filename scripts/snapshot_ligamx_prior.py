from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ligamx edge.html"
OUT_DIR = ROOT / "data" / "cache" / "ligamx_prior"
OUT = OUT_DIR / "v29_embedded_models.json"

MARKER = "const MODELS = "


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source model: {SOURCE}")

    html = SOURCE.read_text(encoding="utf-8")
    idx = html.find(MARKER)
    if idx < 0:
        raise SystemExit("Could not find embedded MODELS object in ligamx edge.html")

    raw = html[idx + len(MARKER):].lstrip()
    models, _ = json.JSONDecoder().raw_decode(raw)

    liga = models.get("ligamx")
    if not isinstance(liga, dict):
        raise SystemExit("Embedded MODELS object does not contain a ligamx model")

    meta = liga.get("meta", {})
    if not liga.get("teams") or not liga.get("league"):
        raise SystemExit("Embedded Liga MX model is incomplete; refusing to snapshot")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(models, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    team_count = len(liga.get("teams", {}))
    split_rows = 0
    for team in liga.get("teams", {}).values():
        split_rows += int(team.get("home", {}).get("n") or 0)
        split_rows += int(team.get("away", {}).get("n") or 0)

    print("Preserved embedded historical model before API refresh:")
    print(f"  source: {SOURCE.name}")
    print(f"  version: {meta.get('version')}")
    print(f"  built: {meta.get('built')}")
    print(f"  meta.matches: {meta.get('matches')}")
    print(f"  teams: {team_count}")
    print(f"  summed home/away team samples: {split_rows}")
    print(f"  snapshot: {OUT}")
    print("  full MODELS object preserved, including Liga MX + Leagues Cup data")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description="Export collected Liga MX slate into a tracked, shareable JSON file.")
    p.add_argument("--date", required=True)
    args = p.parse_args()

    key = args.date.replace("-", "_")
    src = ROOT / "data" / "cache" / "ligamx_tonight" / f"{key}.json"
    if not src.exists():
        raise SystemExit(f"Missing collected slate: {src}")

    payload = json.loads(src.read_text(encoding="utf-8"))

    # Sanity guard: exported collector data should never contain secrets.
    text = json.dumps(payload, ensure_ascii=False)
    forbidden = ("API_FOOTBALL_KEY", "x-apisports-key", "RAPIDAPI_KEY")
    if any(token in text for token in forbidden):
        raise SystemExit("Refusing export: possible secret marker detected.")

    out_dir = ROOT / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"ligamx_{key}_api.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Exported Liga MX API slate to {out}")


if __name__ == "__main__":
    main()

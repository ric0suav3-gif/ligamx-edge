from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_ucl_mobile_ui import DEFAULT_OUTPUT, TEMPLATE, build_payload


AH_BUGGY = "function move(bucket,key,d){state[bucket][key]=Math.max(0,+(state[bucket][key]+d).toFixed(2));render();}"
AH_FIXED = "function move(bucket,key,d){const n=+(state[bucket][key]+d).toFixed(2);state[bucket][key]=bucket==='ah'?n:Math.max(0,n);render();}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the self-contained UCL Edge iPhone page from today's local API-Football caches."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = build_payload()
    template = TEMPLATE.read_text(encoding="utf-8")
    template = template.replace(AH_BUGGY, AH_FIXED)

    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = template.replace("__UCL_DATA__", blob)
    if "__UCL_DATA__" in html:
        raise SystemExit("UI data placeholder was not replaced")

    args.output.write_text(html, encoding="utf-8")
    print(f"Refreshed {args.output}")
    print(f"Slate: {payload['meta']['date']} | fixtures={len(payload['fixtures'])}")
    print(f"Current API-Football market candidates embedded={len(payload['global_picks'])}")
    print("Secrets embedded: none")


if __name__ == "__main__":
    main()

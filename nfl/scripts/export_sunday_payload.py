from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HTML = ROOT / "NFL_Edge_iPhone.html"


def extract_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker = "const D="
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"Could not find embedded Sunday payload in {path}")
    start += len(marker)
    end = text.find(";\n", start)
    if end < 0:
        raise SystemExit("Could not find end of embedded Sunday payload")
    return json.loads(text[start:end])


def main() -> None:
    ap = argparse.ArgumentParser(description="Export the embedded NFL Sunday API/model card as tracked JSON.")
    ap.add_argument("--date", required=True)
    ap.add_argument("--html", type=Path, default=DEFAULT_HTML)
    args = ap.parse_args()

    html = args.html if args.html.is_absolute() else ROOT / args.html
    payload = extract_payload(html)
    out = ROOT / "exports" / f"nfl_sunday_{args.date.replace('-', '_')}_api.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for marker in ("NFL_API_KEY", "x-apisports-key"):
        if marker in text:
            raise SystemExit(f"Refusing to export secret marker: {marker}")
    out.write_text(text, encoding="utf-8")
    print(f"Exported Sunday card: {out}")
    print(f"games={payload['meta']['games']} priced={payload['meta']['priced_games']} straights={len(payload.get('straights') or [])} parlays={len(payload.get('parlays') or [])}")
    print("\nFINAL STRAIGHTS")
    for i,row in enumerate(payload.get("straights") or [], 1):
        print(
            f"  {i}. {row['market']} | p={row.get('selection_probability', row.get('probability', 0)):.1%} "
            f"| fair={row['fair']:.2f} | median={row['median_odd']:.2f} "
            f"| best={row['best_odd']:.2f} {row['best_book']} | books={row['books']} "
            f"| EV={row['consensus_ev']:+.1%}"
        )
    print("\n2-LEG PARLAYS")
    for i,row in enumerate(payload.get("parlays") or [], 1):
        print(
            f"  P{i}: price={row['price']:.2f} | p={row['probability']:.1%} "
            f"| fair={row['fair']:.2f} | edge={row['edge']:+.1%}"
        )
        for leg in row.get("legs") or []:
            print(
                f"      - {leg['market']} | {leg['median_odd']:.2f} "
                f"| p={leg.get('selection_probability', leg.get('probability', 0)):.1%}"
            )


if __name__ == "__main__":
    main()

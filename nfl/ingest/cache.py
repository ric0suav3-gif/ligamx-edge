from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = ROOT / "nfl" / "data" / "cache"


def _path(kind: str, key: str) -> Path:
    safe_kind = kind.strip("/").replace("..", "_")
    safe_key = key.replace("/", "_").replace("..", "_")
    return CACHE_ROOT / safe_kind / f"{safe_key}.json"


def load_json(kind: str, key: str) -> Any | None:
    path = _path(kind, key)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(kind: str, key: str, value: Any) -> Path:
    path = _path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2, sort_keys=False)
    temp.replace(path)
    return path

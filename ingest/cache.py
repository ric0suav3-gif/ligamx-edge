from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = Path("data/cache")


def cache_path(kind: str, key: str, root: Path = DEFAULT_CACHE_DIR) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return root / kind / f"{safe}.json"


def load_json(kind: str, key: str, root: Path = DEFAULT_CACHE_DIR) -> Any | None:
    path = cache_path(kind, key, root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(kind: str, key: str, value: Any, root: Path = DEFAULT_CACHE_DIR) -> Path:
    path = cache_path(kind, key, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path

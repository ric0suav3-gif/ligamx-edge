from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repository root is importable when pytest chooses nfl/ as rootdir
# or when tests are invoked from different working directories.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

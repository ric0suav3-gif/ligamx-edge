from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nfl.ingest.api_sports import APINFLClient


def main() -> None:
    client = APINFLClient()
    result = client.status()
    row = result.response[0] if result.response else {}

    subscription = row.get("subscription") or {}
    requests = row.get("requests") or {}

    print("API-NFL account status")
    print(f"plan: {subscription.get('plan')}")
    print(f"active: {subscription.get('active')}")
    print(f"subscription end: {subscription.get('end')}")
    print(
        f"requests today: {requests.get('current')} / "
        f"{requests.get('limit_day')}"
    )
    print("Personal account fields are intentionally not printed.")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    cmd = [sys.executable, *args]
    print("\n" + "=" * 100)
    print("RUN:", " ".join(cmd))
    print("=" * 100)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare, project and compare one UCL slate end-to-end."
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--matches", type=int, default=30)
    parser.add_argument("--ucl-matches", type=int, default=20)
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()

    run("scripts/setup_ucl_slate.py", "--date", args.date, "--season", str(args.season))
    run("scripts/backfill_domestic_history.py", "--matches", str(args.matches), "--cutoff", args.date)
    run("scripts/build_team_profiles.py")
    run("scripts/build_stat_baselines.py", "--cutoff", args.date)
    run("scripts/backfill_ucl_team_history.py", "--matches", str(args.ucl_matches), "--cutoff", args.date)
    run("scripts/build_stat_transfers.py")
    run("scripts/predict_stat_markets.py")
    run("scripts/audit_odds_markets.py")
    run("scripts/compare_stat_edges.py", "--top", str(args.top))

    print("\n" + "=" * 100)
    print("DONE")
    print("Paste the final SAFE TEAM-TOTAL MODE table into ChatGPT.")
    print("=" * 100)


if __name__ == "__main__":
    main()

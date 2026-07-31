"""The daily run: pull the feeds, expire dead listings, score the three tiers.

This is the single source of truth for what a daily run does. Both entry points
go through it — `run_daily.sh` for manual use and the LaunchAgent for the
scheduled run — so the two can never drift.

It is a Python entry point rather than a shell script for a specific reason.
The repo lives under ~/Desktop, which macOS protects with TCC, and a LaunchAgent
running /bin/bash is denied read access to files there: launchd invoking
`/bin/bash run_daily.sh` fails with "Operation not permitted" before the script
ever starts. The venv interpreter is not subject to that denial and reads the
repo fine, so driving the run from Python keeps bash out of the scheduled path
entirely. See deploy/README.md.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.resolve()
PY = REPO / "venv" / "bin" / "python"

# Tier order is priority order: if a run dies partway, the most on-target jobs
# are already scored. tier3 (solutions_engineering) is the primary target shape
# and must run before the broad keyword tier.
#
# --limit caps unattended spend during a cycle-opening surge; anything past the
# cap stays queued for the next run.
STEPS = [
    ["pull.py"],
    ["match_batch.py", "tier1", "--limit", "60"],
    ["match_batch.py", "tier3", "--limit", "60"],
    ["match_batch.py", "tier2", "--limit", "60"],
]


def main() -> int:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"=== mathetes daily run: {stamp} ===", flush=True)

    if not PY.exists():
        print(f"FATAL: venv interpreter missing at {PY}", file=sys.stderr, flush=True)
        return 1

    for step in STEPS:
        print(f"\n--- {' '.join(step)} ---", flush=True)
        # cwd matters: match_batch.py loads .env relative to the working dir.
        result = subprocess.run([str(PY), *step], cwd=REPO)
        if result.returncode != 0:
            print(f"FATAL: {' '.join(step)} exited {result.returncode}",
                  file=sys.stderr, flush=True)
            return result.returncode

    done = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"\n=== done: {done} ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

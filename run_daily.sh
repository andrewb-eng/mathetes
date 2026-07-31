#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use the venv interpreter directly rather than `source venv/bin/activate`.
# launchd runs this with a minimal, non-interactive environment where relying
# on activate's shell side effects is fragile; calling the interpreter by path
# is equivalent and has no such dependency.
PY="$SCRIPT_DIR/venv/bin/python"

echo "=== mathetes daily run: $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

"$PY" pull.py

# Tier order is priority order: if a run dies partway, the most on-target jobs
# are already scored. tier3 (solutions_engineering) is the primary target shape
# and must run before the broad keyword tier — it was never invoked here at all,
# which is why that tier had scored nothing.
# --limit caps unattended spend during a cycle-opening surge; whatever is left
# over stays queued for tomorrow.
"$PY" match_batch.py tier1 --limit 60
"$PY" match_batch.py tier3 --limit 60
"$PY" match_batch.py tier2 --limit 60

echo "=== done: $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

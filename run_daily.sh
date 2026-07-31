#!/usr/bin/env bash
# Manual entry point for the daily run. The actual steps live in daily.py so
# this and the LaunchAgent can never drift — see the note there about why the
# scheduled path cannot go through bash.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/daily.py" "$@"

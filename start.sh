#!/usr/bin/env bash
# Start the BiteLearning web UI.
# Usage: ./start.sh [--port 8000] [--host 127.0.0.1]

set -euo pipefail

# Resolve the project directory regardless of where this script is invoked from.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
  echo "No .venv found in $DIR - run the setup steps from the project README first." >&2
  exit 1
fi

source .venv/bin/activate
python scripts/run_web.py "$@"

#!/usr/bin/env bash
# Start a local/intranet Manager instance for React shell acceptance.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PORT:-8770}"
STATE="${STATE_ROOT:-/tmp/ft-manager-state}"
DATA="${DATA_ROOT:-/tmp/ft-manager-data}"
PYTHON="${PYTHON:-python3}"
mkdir -p "$STATE" "$DATA"
exec "$PYTHON" -m server.manager.app \
  --repo "$ROOT" \
  --host "${HOST:-0.0.0.0}" \
  --port "$PORT" \
  --state-root "$STATE" \
  --data-root "$DATA" \
  --server-role main

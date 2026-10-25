#!/usr/bin/env bash
# Send only changed Nautilus source files to the build host.
# The remote cargo target is deliberately excluded from deletion and transfer.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${NAUTILUS_SRC:-$ROOT/vendor/nautilus_trader}"
TARGET="${NAUTILUS_BUILD_TARGET:-launch-advisor:/data/nautilus-build}"
[ -f "$SRC/python/pyproject.toml" ] || { echo "missing $SRC/python/pyproject.toml" >&2; exit 1; }
git -C "$SRC" diff --quiet || { echo "vendor/nautilus_trader has uncommitted changes" >&2; exit 1; }
echo "syncing $(git -C "$SRC" rev-parse HEAD) to $TARGET"
rsync -az --delete \
  --exclude target --exclude .git --exclude __pycache__ \
  "$SRC/" "$TARGET/"

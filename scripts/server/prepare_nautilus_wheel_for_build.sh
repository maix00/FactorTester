#!/usr/bin/env bash
# Copy the wheel cached for the current local submodule commit into the Docker
# build context and print the required build argument.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${NAUTILUS_SRC:-$ROOT/vendor/nautilus_trader}"
WHEEL_DIR="${NAUTILUS_WHEEL_DIR:-$ROOT/.artifacts/nautilus-wheels}"
DEST="$ROOT/deploy/docker/factortester-public/wheels"
REVISION="$(git -C "$SRC" rev-parse HEAD)"
WHEEL="$WHEEL_DIR/nautilus_trader-$REVISION.whl"
[ -f "$WHEEL" ] || { echo "missing cached wheel for $REVISION: $WHEEL" >&2; exit 1; }
mkdir -p "$DEST"
rm -f "$DEST"/nautilus_trader-*.whl
cp -f "$WHEEL" "$DEST/"
echo "NAUTILUS_WHEEL_REQUIRED=1"
ls -lh "$DEST"/nautilus_trader-*.whl

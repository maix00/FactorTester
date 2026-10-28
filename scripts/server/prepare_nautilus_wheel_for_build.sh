#!/usr/bin/env bash
# Stage the canonical wheel produced for this exact composed runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${NAUTILUS_SRC:-$ROOT/vendor/nautilus_trader}"
WHEEL_DIR="${NAUTILUS_WHEEL_DIR:-$ROOT/.artifacts/nautilus-wheels}"
DEST="$ROOT/deploy/docker/factortester-public/wheels"
source "$ROOT/scripts/server/nautilus_build_identity.sh"
BUILD_ID="$(nautilus_build_identity "$ROOT" "$SRC" "${NAUTILUS_BUILD_PLATFORM:-linux/amd64}")"
shopt -s nullglob
wheels=("$WHEEL_DIR/$BUILD_ID"/nautilus_trader-*-*-*-*.whl)
[[ ${#wheels[@]} -eq 1 ]] || { echo "expected one canonical composed runtime wheel for $BUILD_ID" >&2; exit 1; }
# Validate before changing the current Docker build context. Hash-named cache
# aliases are deliberately never pip inputs.
python - "${wheels[0]}" <<'PY'
import sys,zipfile
from pathlib import Path
from email.parser import BytesParser
path=Path(sys.argv[1])
with zipfile.ZipFile(path) as wheel:
    names=[name for name in wheel.namelist() if name.endswith('.dist-info/METADATA')]
    if len(names)!=1:raise SystemExit('invalid wheel metadata')
    metadata=BytesParser().parsebytes(wheel.read(names[0]))
    if metadata['Name'].replace('-','_')!='nautilus_trader':raise SystemExit('unexpected wheel distribution')
PY
mkdir -p "$DEST"
staged="$(mktemp "$DEST/.nautilus-stage.XXXXXX")"
trap 'rm -f "$staged"' EXIT
cp -f "${wheels[0]}" "$staged"
rm -f "$DEST"/nautilus_trader-*.whl
mv -f "$staged" "$DEST/$(basename "${wheels[0]}")"
echo "NAUTILUS_WHEEL_REQUIRED=1"
ls -lh "$DEST/$(basename "${wheels[0]}")"

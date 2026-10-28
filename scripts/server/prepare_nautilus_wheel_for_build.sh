#!/usr/bin/env bash
# Immutable, separately transported BuildKit context; never modify tracked wheels.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${NAUTILUS_SRC:-$ROOT/vendor/nautilus_trader}"
WHEEL_DIR="${NAUTILUS_WHEEL_DIR:-$ROOT/.artifacts/nautilus-wheels}"
DEST_ROOT="${NAUTILUS_DEPLOY_WHEEL_ROOT:-$ROOT/.artifacts/deployment-wheels}"
source "$ROOT/scripts/server/nautilus_build_identity.sh"
BUILD_ID="$(nautilus_build_identity "$ROOT" "$SRC" "${NAUTILUS_BUILD_PLATFORM:-linux/amd64}")"
ALPHA_REVISION="$(git -C "$ROOT/vendor/py-alpha-lib" rev-parse HEAD)"
shopt -s nullglob
native=("$WHEEL_DIR/$BUILD_ID"/nautilus_trader-*-*-*-*.whl)
alpha=("$WHEEL_DIR/alpha-$ALPHA_REVISION"/py_alpha_lib-*-*-*-*.whl)
[[ ${#native[@]} -eq 1 && ${#alpha[@]} -eq 1 ]] || { echo "expected canonical alpha and composed runtime wheels for $BUILD_ID" >&2; exit 1; }
python3 - "${native[0]}" "${alpha[0]}" <<'PY'
import sys,zipfile
from email.parser import BytesParser
for path,expected in zip(sys.argv[1:],['nautilus_trader','py_alpha_lib']):
    with zipfile.ZipFile(path) as wheel:
        names=[name for name in wheel.namelist() if name.endswith('.dist-info/METADATA')]
        if len(names)!=1:raise SystemExit('invalid wheel metadata')
        metadata=BytesParser().parsebytes(wheel.read(names[0]))
        if metadata['Name'].replace('-','_')!=expected:raise SystemExit('unexpected wheel distribution')
PY
mkdir -p "$DEST_ROOT"
DEST="$DEST_ROOT/$BUILD_ID"
if [[ -f "$DEST/checksums.sha256" ]] && (cd "$DEST" && shasum -a 256 -c checksums.sha256 >/dev/null 2>&1); then
  echo "$DEST"; exit 0
fi
[[ ! -e "$DEST" ]] || { echo "existing artifact context is invalid; preserve it for inspection: $DEST" >&2; exit 1; }
staged="$(mktemp -d "$DEST_ROOT/.stage.XXXXXX")"
trap 'rm -rf "$staged"' EXIT
for wheel in "${native[0]}" "${alpha[0]}"; do
  ln "$wheel" "$staged/$(basename "$wheel")" 2>/dev/null || cp "$wheel" "$staged/"
done
printf '%s\n' "$BUILD_ID" > "$staged/build-id.txt"
(cd "$staged" && shasum -a 256 ./*.whl > checksums.sha256)
mv "$staged" "$DEST"
echo "$DEST"

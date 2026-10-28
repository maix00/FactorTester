#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
wheel="${1:?wheel required}"
if python3 - "$wheel" <<'PY'
from zipfile import ZipFile
import sys
with ZipFile(sys.argv[1]) as wheel:
    required={'nautilus_trader/__init__.py','nautilus_trader/_fixup.py','nautilus_trader/backtest/__init__.py','nautilus_trader/analysis/tearsheet.py'}
    raise SystemExit(0 if required.issubset(wheel.namelist()) else 1)
PY
then exit 0; fi
CACHE="${NAUTILUS_CACHE:-$ROOT/.artifacts/nautilus-build}"
mkdir -p "$CACHE"
source_snapshot="$(mktemp -d "$CACHE/package.XXXXXX")"
trap 'rm -rf "$source_snapshot"' EXIT
revision="$(git -C "$ROOT/vendor/nautilus_trader" rev-parse HEAD)"
git -C "$ROOT/vendor/nautilus_trader" archive "$revision" python/nautilus_trader | tar -xf - -C "$source_snapshot"
docker run --rm --platform "${NAUTILUS_BUILD_PLATFORM:-linux/amd64}" --memory=1g --cpus=1 \
  -v "$source_snapshot/python/nautilus_trader:/source:ro" \
  -v "$(cd "$(dirname "$wheel")" && pwd):/wheels" \
  -v "$ROOT/scripts/server/complete_nautilus_wheel.py:/pack.py:ro" \
  -e WHEEL_NAME="$(basename "$wheel")" \
  "${NAUTILUS_BUILDER_IMAGE:-traderesearch/nautilus-builder:py314-amd64}" \
  bash -lc 'python -m pip install --quiet wheel==0.45.1 && python /pack.py --wheel "/wheels/$WHEEL_NAME" --source /source'
echo "native packaging=completed native_recompiled=false"

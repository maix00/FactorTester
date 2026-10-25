#!/usr/bin/env bash
# Install and smoke-test a wheel built from vendor/nautilus_trader.
set -euo pipefail
WHEEL="${1:?usage: install_nautilus_local_wheel.sh <wheel>}"
PYTHON="${PYTHON:-python3}"
[ -f "$WHEEL" ] || { echo "missing wheel: $WHEEL" >&2; exit 1; }
"$PYTHON" -m pip install --no-cache-dir --no-deps --force-reinstall "$WHEEL"
"$PYTHON" - <<'PY'
import nautilus_trader
from nautilus_trader.core import UUID4
print("nautilus_trader", nautilus_trader.__version__, "uuid", UUID4())
PY

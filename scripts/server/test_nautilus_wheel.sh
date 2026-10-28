#!/usr/bin/env bash
# Smoke-test a locally built wheel inside the public runtime image.
set -euo pipefail
WHEEL="${1:?usage: test_nautilus_wheel.sh <wheel>}"
IMAGE="${FACTORTESTER_IMAGE:-factortester-public:ae67b22a0f98b37454bc8a8ef03682eb7b1a4162}"
[ -f "$WHEEL" ] || { echo "missing wheel: $WHEEL" >&2; exit 1; }
docker run --rm -v "$(cd "$(dirname "$WHEEL")" && pwd):/wheels:ro" "$IMAGE" bash -lc '
  set -euo pipefail
  wheel="$(ls /wheels/nautilus_trader-*.whl | head -n 1)"
  python -m pip install --no-cache-dir --no-deps "$wheel"
  python - <<"PY"
import nautilus_trader
print("nautilus_trader", nautilus_trader.__version__)
from nautilus_trader.model.identifiers import InstrumentId
print("instrument id ok", InstrumentId.from_str("ES.GLBX"))
PY
'

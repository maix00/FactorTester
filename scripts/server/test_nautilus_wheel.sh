#!/usr/bin/env bash
# Smoke-test a locally built wheel inside the public runtime image.
set -euo pipefail
WHEEL="${1:?usage: test_nautilus_wheel.sh <wheel>}"
IMAGE="${FACTORTESTER_IMAGE:?set FACTORTESTER_IMAGE to the reviewed runtime image}"
[ -f "$WHEEL" ] || { echo "missing wheel: $WHEEL" >&2; exit 1; }
docker run --rm --platform "${NAUTILUS_BUILD_PLATFORM:-linux/amd64}" \
  --network none --memory=1g --memory-swap=1g --cpus=1 --entrypoint bash \
  -v "$(cd "$(dirname "$WHEEL")" && pwd):/wheels:ro" \
  -e "NAUTILUS_SMOKE_WHEEL=$(basename "$WHEEL")" "$IMAGE" -lc '
  set -euo pipefail
  python -m pip install --no-index --no-cache-dir --no-deps --quiet \
    --root-user-action=ignore "/wheels/$NAUTILUS_SMOKE_WHEEL"
  python - <<"PY"
import json
import nautilus_trader
from nautilus_trader import _libnautilus as native
from nautilus_trader.model import InstrumentId
from nautilus_trader.backtest import BacktestEngine
assert InstrumentId.from_str("T2403.CFFEX").value == "T2403.CFFEX"
assert callable(BacktestEngine)
assert callable(native.attach_factor_family)
assert callable(native.replay_shared_inputs)
assert native.FACTOR_OBSERVED_SOURCE_ORDINAL_VERSION == 1
print(json.dumps({"linux_native_import": True, "version": nautilus_trader.__version__,
                  "factor_family_bridge": True, "shared_replay": True, "observed_source_ordinal_version": 1}))
PY
'

#!/usr/bin/env bash
# Build the local vendor/nautilus_trader submodule into a Linux wheel.
# Run on an x86_64 Linux host (the public worker architecture), not on arm64.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${NAUTILUS_SRC:-$ROOT/vendor/nautilus_trader}"
OUT="${NAUTILUS_WHEEL_DIR:-$ROOT/.artifacts/nautilus-wheels}"
CACHE="${NAUTILUS_CACHE:-$ROOT/.artifacts/nautilus-build}"
JOBS="${CARGO_BUILD_JOBS:-1}"
MEMORY="${NAUTILUS_BUILD_MEMORY:-3g}"
BUILDER="${NAUTILUS_BUILDER_IMAGE:-traderesearch/nautilus-builder:py314}"
# nautilus-model is a large staticlib; codegen-units=1 exceeded a 3 GiB
# container. Sixteen units keep the peak below that budget on the public host.
mkdir -p "$OUT" "$CACHE/cargo/registry" "$CACHE/cargo/git"
[ -f "$SRC/python/Cargo.toml" ] || { echo "missing $SRC/python/Cargo.toml" >&2; exit 1; }
git -C "$SRC" diff --quiet || { echo "vendor/nautilus_trader has uncommitted changes" >&2; exit 1; }
REVISION="$(git -C "$SRC" rev-parse HEAD)"
CACHED="$OUT/nautilus_trader-$REVISION.whl"
if [ -f "$CACHED" ]; then
  echo "cached wheel for $REVISION: $CACHED"
  exit 0
fi
echo "building nautilus_trader from local commit $REVISION"

if ! docker image inspect "$BUILDER" >/dev/null 2>&1; then
  docker build -t "$BUILDER" \
    -f "$ROOT/deploy/docker/factortester-public/NautilusBuilder.Dockerfile" \
    "$ROOT/deploy/docker/factortester-public"
fi

docker run --rm \
  --memory="$MEMORY" --memory-swap="$MEMORY" --cpus="${NAUTILUS_BUILD_CPUS:-2}" \
  -e CARGO_PROFILE_RELEASE_CODEGEN_UNITS="${NAUTILUS_CODEGEN_UNITS:-16}" \
  -v "$SRC:/src" -v "$OUT:/wheels" \
  -v "$CACHE/cargo/registry:/root/.cargo/registry" \
  -v "$CACHE/cargo/git:/root/.cargo/git" \
  "$BUILDER" bash -lc '
    set -euo pipefail
    . /root/.cargo/env
    cd /src/python
    CARGO_BUILD_JOBS='"$JOBS"' maturin build --release --out /wheels -i python3.14
  '
WHEEL="$(ls "$OUT"/nautilus_trader-*.whl | head -n 1)"
cp -f "$WHEEL" "$CACHED"
ls -lh "$WHEEL" "$CACHED"

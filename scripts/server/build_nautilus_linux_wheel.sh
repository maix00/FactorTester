#!/usr/bin/env bash
# Build the local vendor/nautilus_trader submodule into a Linux wheel.
# Run on an x86_64 Linux host (the public worker architecture), not on arm64.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${NAUTILUS_SRC:-$ROOT/vendor/nautilus_trader}"
OUT="${NAUTILUS_WHEEL_DIR:-$ROOT/.artifacts/nautilus-wheels}"
CACHE="${NAUTILUS_CACHE:-$ROOT/.artifacts/nautilus-build}"
TARGET_CACHE="${NAUTILUS_TARGET_CACHE:-$CACHE/target}"
JOBS="${CARGO_BUILD_JOBS:-1}"
MEMORY="${NAUTILUS_BUILD_MEMORY:-3g}"
PLATFORM="${NAUTILUS_BUILD_PLATFORM:-linux/amd64}"
BUILDER="${NAUTILUS_BUILDER_IMAGE:-traderesearch/nautilus-builder:py314-amd64}"
# nautilus-model is a large staticlib; codegen-units=1 exceeded a 3 GiB
# container. Sixteen units keep the peak below that budget on the public host.
mkdir -p "$OUT" "$CACHE/cargo/registry" "$CACHE/cargo/git" "$TARGET_CACHE"
bash "$ROOT/scripts/server/check_local_build_capacity.sh"
cleanup_target() {
  # The target directory is build state, not a deliverable.  Leaving a 100 GiB
  # debug/incremental tree behind has already exhausted the local disk once.
  rm -rf -- "$TARGET_CACHE"
  if [[ -n "${BUILD_SRC:-}" ]]; then rm -rf -- "$BUILD_SRC"; fi
}
trap cleanup_target EXIT
[ -f "$SRC/python/pyproject.toml" ] || { echo "missing $SRC/python/pyproject.toml" >&2; exit 1; }
git -C "$SRC" diff --quiet || { echo "vendor/nautilus_trader has uncommitted changes" >&2; exit 1; }
[[ "$(cd "$SRC" && pwd -P)" == "$(cd "$ROOT/vendor/nautilus_trader" && pwd -P)" ]] || {
  echo "composed runtime requires this checkout's pinned Nautilus submodule" >&2; exit 1;
}
git -C "$ROOT/vendor/py-alpha-lib" diff --quiet HEAD || {
  echo "alpha submodule has uncommitted changes" >&2; exit 1;
}
REVISION="$(git -C "$SRC" rev-parse HEAD)"
ALPHA_REVISION="$(git -C "$ROOT/vendor/py-alpha-lib" rev-parse HEAD)"
git -C "$ROOT" diff --quiet HEAD -- native/traderesearch_nautilus_runtime traderesearch_data/rust || {
  echo "runtime composition has uncommitted changes" >&2; exit 1;
}
RUNTIME_TREE="$(git -C "$ROOT" ls-tree -r HEAD -- native/traderesearch_nautilus_runtime traderesearch_data/rust)"
BUILD_ID="$(printf '%s\n' "$REVISION" "$ALPHA_REVISION" "$RUNTIME_TREE" "$PLATFORM" | shasum -a 256 | cut -d' ' -f1)"
BUILD_OUT="$OUT/$BUILD_ID"
ALPHA_OUT="$OUT/alpha-$ALPHA_REVISION"
mkdir -p "$BUILD_OUT" "$ALPHA_OUT"
CACHED="$OUT/nautilus_trader-$BUILD_ID.whl"
if [ -f "$CACHED" ]; then
  echo "cached wheel for $REVISION: $CACHED"
  exit 0
fi
# Never build on the public application host. It must pull a finished wheel
# from the intranet builder; a 3 GiB Rust build alongside CouchDB/app caused an
# unreachable public host.
if { docker ps --format '{{.Names}}' | grep -q 'factortester-public-factortester-public' \
     || docker ps --format '{{.Names}}' | grep -q 'factortester-couchdb'; } \
   && [ "${NAUTILUS_BUILD_ALLOW_SHARED:-0}" != "1" ]; then
  echo "refusing to build Nautilus on the public application host" >&2
  echo "CouchDB/app must both be stopped; use an intranet builder instead" >&2
  echo "or set NAUTILUS_BUILD_ALLOW_SHARED=1 explicitly" >&2
  exit 1
fi
if [ -r /proc/meminfo ]; then
  available_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
  if [ -n "${available_kb:-}" ] && [ "$available_kb" -lt 6291456 ]; then
    echo "refusing Nautilus build: less than 5 GiB available memory" >&2
    exit 1
  fi
fi
echo "building nautilus_trader from local commit $REVISION"
# Compile immutable committed inputs even when another agent edits the checkout.
BUILD_SRC="$(mktemp -d "$CACHE/source-$BUILD_ID.XXXXXX")"
mkdir -p "$BUILD_SRC/vendor/nautilus_trader" "$BUILD_SRC/vendor/py-alpha-lib"
git -C "$ROOT" archive HEAD native/traderesearch_nautilus_runtime traderesearch_data/rust | tar -xf - -C "$BUILD_SRC"
git -C "$SRC" archive "$REVISION" | tar -xf - -C "$BUILD_SRC/vendor/nautilus_trader"
git -C "$ROOT/vendor/py-alpha-lib" archive "$ALPHA_REVISION" | tar -xf - -C "$BUILD_SRC/vendor/py-alpha-lib"


if ! docker image inspect "$BUILDER" >/dev/null 2>&1; then
  docker build --platform "$PLATFORM" -t "$BUILDER" \
    -f "$ROOT/deploy/docker/factortester-public/NautilusBuilder.Dockerfile" \
    "$ROOT/deploy/docker/factortester-public"
fi

docker run --rm --platform "$PLATFORM" \
  --memory="$MEMORY" --memory-swap="$MEMORY" --cpus="${NAUTILUS_BUILD_CPUS:-2}" \
  -e CARGO_PROFILE_RELEASE_CODEGEN_UNITS="${NAUTILUS_CODEGEN_UNITS:-16}" \
  -v "$BUILD_SRC:/repo" -v "$BUILD_OUT:/wheels" -v "$ALPHA_OUT:/alpha-wheels" \
  -v "$CACHE/cargo/registry:/root/.cargo/registry" \
  -v "$CACHE/cargo/git:/root/.cargo/git" \
  -v "$TARGET_CACHE:/target" \
  -e CARGO_TARGET_DIR=/target \
  -e CARGO_INCREMENTAL=0 \
  -e CARGO_PROFILE_RELEASE_DEBUG=0 \
  -e CARGO_PROFILE_RELEASE_STRIP=symbols \
  "$BUILDER" bash -lc '
    set -euo pipefail
    . /root/.cargo/env
    cd /repo/vendor/py-alpha-lib/py-binding
    CARGO_BUILD_JOBS='"$JOBS"' maturin build --release --out /alpha-wheels -i python3.14
    cd /repo/native/traderesearch_nautilus_runtime
    CARGO_BUILD_JOBS='"$JOBS"' maturin build --release --out /wheels -i python3.14
  '
WHEEL="$(ls "$BUILD_OUT"/nautilus_trader-*.whl | head -n 1)"
cp -f "$WHEEL" "$CACHED"
ls -lh "$WHEEL" "$CACHED"

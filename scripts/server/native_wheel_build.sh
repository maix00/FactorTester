#!/usr/bin/env bash
# Build the local vendor/nautilus_trader submodule into a Linux wheel.
# Run on an x86_64 Linux host (the public worker architecture), not on arm64.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="${NAUTILUS_SRC:-$ROOT/vendor/nautilus_trader}"
OUT="${NAUTILUS_WHEEL_DIR:-$ROOT/.artifacts/nautilus-wheels}"
CACHE="${NAUTILUS_CACHE:-$ROOT/.artifacts/nautilus-build}"
TARGET_CACHE="${NAUTILUS_TARGET_CACHE:-$CACHE/target-reusable}"
JOBS="${CARGO_BUILD_JOBS:-1}"
MEMORY="${NAUTILUS_BUILD_MEMORY:-3g}"
PLATFORM="${NAUTILUS_BUILD_PLATFORM:-linux/amd64}"
BUILDER="${NAUTILUS_BUILDER_IMAGE:-traderesearch/nautilus-builder:py314-amd64}"
# nautilus-model is a large staticlib; codegen-units=1 exceeded a 3 GiB
# container. Sixteen units keep the peak below that budget on the public host.
mkdir -p "$OUT" "$CACHE"
if [[ "${TR_NATIVE_BUILD_LOCK_HELD:-0}" != "1" ]]; then
  exec python3 "$ROOT/scripts/server/native_build_lock.py" "$CACHE/.build.lock" bash "$0" "$@"
fi
cleanup_snapshot() {
  if [[ -n "${ARCHIVE_SRC:-}" ]]; then rm -rf -- "$ARCHIVE_SRC"; fi
}
trap cleanup_snapshot EXIT
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
source "$ROOT/scripts/server/nautilus_build_identity.sh"
BUILD_ID="$(nautilus_build_identity "$ROOT" "$SRC" "$PLATFORM")"
BUILD_OUT="$OUT/$BUILD_ID"
ALPHA_OUT="$OUT/alpha-$ALPHA_REVISION"
mkdir -p "$BUILD_OUT" "$ALPHA_OUT"
if [[ -f "$BUILD_OUT/checksums.sha256" ]] && shasum -a 256 -c "$BUILD_OUT/checksums.sha256" >/dev/null 2>&1; then
  WHEEL="$(ls "$BUILD_OUT"/nautilus_trader-*.whl | head -n 1)"
  bash "$ROOT/scripts/server/complete_nautilus_wheel.sh" "$WHEEL"
  ALPHA_WHEEL="$(ls "$ALPHA_OUT"/py_alpha_lib-*.whl | head -n 1)"
  shasum -a 256 "$WHEEL" "$ALPHA_WHEEL" > "$BUILD_OUT/checksums.sha256"
  echo "native wheel cache=hit build_id=$BUILD_ID platform=$PLATFORM"
  exit 0
fi
echo "native wheel cache=miss build_id=$BUILD_ID reason=missing-or-invalid-wheel-receipt"
bash "$ROOT/scripts/server/check_local_build_capacity.sh"
mkdir -p "$CACHE/cargo/registry" "$CACHE/cargo/git" "$TARGET_CACHE"
cache_kb="$(du -sk "$TARGET_CACHE" | awk '{print $1}')"
limit_gb="${NAUTILUS_TARGET_CACHE_MAX_GB:-4}"
[[ "$limit_gb" =~ ^[1-9][0-9]*$ ]] || { echo "invalid target cache budget" >&2; exit 2; }
if (( cache_kb > limit_gb * 1024 * 1024 )); then
  echo "native target cache exceeds ${limit_gb}GiB; explicit cache maintenance required: $TARGET_CACHE" >&2
  exit 3
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
ARCHIVE_SRC="$(mktemp -d "$CACHE/archive-$BUILD_ID.XXXXXX")"
BUILD_SRC="$CACHE/source"
mkdir -p "$ARCHIVE_SRC/vendor/nautilus_trader" "$ARCHIVE_SRC/vendor/py-alpha-lib" "$BUILD_SRC"
git -C "$ROOT" archive HEAD native/traderesearch_nautilus_runtime traderesearch_data/rust | tar -xf - -C "$ARCHIVE_SRC"
git -C "$SRC" archive "$REVISION" | tar -xf - -C "$ARCHIVE_SRC/vendor/nautilus_trader"
git -C "$ROOT/vendor/py-alpha-lib" archive "$ALPHA_REVISION" | tar -xf - -C "$ARCHIVE_SRC/vendor/py-alpha-lib"
# Preserve unchanged source mtimes: Cargo can reuse crate artifacts across root
# commits. /repo is the same container path for every build.
rsync -rc --delete "$ARCHIVE_SRC/" "$BUILD_SRC/"
rm -rf -- "$ARCHIVE_SRC"; ARCHIVE_SRC=""


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
  -e CARGO_INCREMENTAL="${NAUTILUS_INCREMENTAL:-1}" \
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
ALPHA_WHEEL="$(ls "$ALPHA_OUT"/py_alpha_lib-*.whl | head -n 1)"
bash "$ROOT/scripts/server/complete_nautilus_wheel.sh" "$WHEEL"
shasum -a 256 "$WHEEL" "$ALPHA_WHEEL" > "$BUILD_OUT/checksums.sha256"
cache_kb="$(du -sk "$TARGET_CACHE" | awk '{print $1}')"
if (( cache_kb > limit_gb * 1024 * 1024 )); then
  # Finished wheels remain authoritative. Prefer the storage budget over a
  # speculative speedup; only this build's owned Cargo target may be evicted.
  if [[ "$TARGET_CACHE" == "$CACHE/target-reusable" ]]; then rm -rf -- "$TARGET_CACHE";
  else echo "external target exceeds budget; left untouched: $TARGET_CACHE" >&2; fi
  echo "native target cache=evicted reason=over-${limit_gb}GiB-budget"
fi
echo "native wheel cache=stored build_id=$BUILD_ID target_cache_kb=$cache_kb"
ls -lh "$WHEEL"

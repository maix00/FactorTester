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
mkdir -p "$OUT" "$CACHE/cargo" "$CACHE/rustup"
[ -f "$SRC/python/Cargo.toml" ] || { echo "missing $SRC/python/Cargo.toml" >&2; exit 1; }
git -C "$SRC" diff --quiet || { echo "vendor/nautilus_trader has uncommitted changes" >&2; exit 1; }
REVISION="$(git -C "$SRC" rev-parse HEAD)"
echo "building nautilus_trader from local commit $REVISION"

docker run --rm \
  --memory="$MEMORY" --memory-swap="$MEMORY" --cpus="${NAUTILUS_BUILD_CPUS:-2}" \
  -e RUSTUP_DIST_SERVER=https://rsproxy.cn \
  -e RUSTUP_UPDATE_ROOT=https://rsproxy.cn/rustup \
  -v "$SRC:/src" -v "$OUT:/wheels" \
  -v "$CACHE/cargo:/root/.cargo" -v "$CACHE/rustup:/root/.rustup" \
  python:3.14-slim bash -lc '
    set -euo pipefail
    sed -i s/deb.debian.org/mirrors.aliyun.com/g /etc/apt/sources.list.d/debian.sources
    apt-get update
    apt-get install -y --no-install-recommends build-essential curl pkg-config libssl-dev patchelf cmake clang
    if [ ! -x /root/.cargo/bin/rustup ]; then
      curl --proto "=https" --tlsv1.2 -sSf https://rsproxy.cn/rustup-init.sh | sh -s -- -y --default-toolchain 1.99.0 --profile minimal
    fi
    . /root/.cargo/env
    python -m pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple maturin==1.15.0
    mkdir -p /root/.cargo
    printf "[source.crates-io]\nreplace-with = \"rsproxy-sparse\"\n[source.rsproxy-sparse]\nregistry = \"sparse+https://rsproxy.cn/index/\"\n" > /root/.cargo/config.toml
    cd /src/python
    CARGO_BUILD_JOBS='"$JOBS"' maturin build --release --out /wheels -i python3.14
  '
ls -lh "$OUT"/nautilus_trader-*.whl

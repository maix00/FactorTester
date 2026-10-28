#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAUTILUS_ROOT="${ROOT_DIR}/vendor/nautilus_trader"
PYTHON_SOURCE="${NAUTILUS_ROOT}/python"
COMPOSITION_ROOT="${ROOT_DIR}/native/traderesearch_nautilus_runtime"
ENV_NAME="${FT_ENV_NAME:-GTHT}"
BUILD_JOBS="${CARGO_BUILD_JOBS:-2}"
HOST_TARGET="${CARGO_TARGET_DIR:-${ROOT_DIR}/.artifacts/nautilus-build/host-target}"
DEV_OPT_LEVEL="${CARGO_PROFILE_DEV_OPT_LEVEL:-1}"

if [[ ! -f "${NAUTILUS_ROOT}/rust-toolchain.toml" || ! -f "${PYTHON_SOURCE}/pyproject.toml" ]]; then
  echo "NautilusTrader submodule is missing; initialize vendor/nautilus_trader first." >&2
  exit 1
fi

EXPECTED_VERSION="$(conda run -n "${ENV_NAME}" python -c \
  'import tomllib, sys; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' \
  "${PYTHON_SOURCE}/pyproject.toml")"
BRIDGE_VERSION="$(conda run -n "${ENV_NAME}" python -c \
  'import runpy, sys; print(runpy.run_path(sys.argv[1])["NAUTILUS_VERSION"])' \
  "${ROOT_DIR}/server/services/nautilus_bridge/version.py" \
  2>/dev/null || true)"

if [[ "${BRIDGE_VERSION}" != "${EXPECTED_VERSION}" ]]; then
  echo "FactorTester pins Nautilus ${BRIDGE_VERSION:-<unavailable>}, but the vendored source is ${EXPECTED_VERSION}." >&2
  echo "Update server/services/nautilus_bridge/version.py before building." >&2
  exit 1
fi

runtime_is_ready() {
  local state
  state="$(conda run --no-capture-output -n "${ENV_NAME}" python -c '
import importlib
import hashlib
import json
import os
from pathlib import Path
import sys

expected_version, expected_source, mode = sys.argv[1:]
try:
    import nautilus_trader
    native = importlib.import_module("nautilus_trader._libnautilus")
except (ImportError, OSError):
    print("needs-build")
    raise SystemExit(0)
source = Path(expected_source).resolve()
package_path = Path(nautilus_trader.__file__).resolve()
native_file = getattr(native, "__file__", None)
if not native_file:
    print("needs-build")
    raise SystemExit(0)
native_path = Path(native_file).resolve()
if nautilus_trader.__version__ != expected_version:
    print("needs-build")
    raise SystemExit(0)
if not package_path.is_relative_to(source) or not native_path.is_relative_to(source):
    print("needs-build")
    raise SystemExit(0)
from nautilus_trader.backtest import BacktestEngine
if (not callable(getattr(BacktestEngine, "run_catalogs", None))
        or not callable(getattr(native, "attach_factor_family", None))
        or not callable(getattr(native, "replay_shared_inputs", None))):
    print("needs-build")
    raise SystemExit(0)
# A matching package version does not imply the local Rust edits are built.
# Only inspect native build inputs; Cargo still owns incremental dependency tracking.
rust_root = source.parent
build_inputs = [rust_root / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
build_inputs.extend(path for path in (rust_root / "crates").rglob("*")
                    if path.suffix in {".rs", ".toml"})
repo_root = rust_root.parent.parent
for folder in (repo_root / "native", repo_root / "traderesearch_data/rust", repo_root / "vendor/py-alpha-lib/alpha-algo", repo_root / "vendor/py-alpha-lib/adapters/nautilus"):
    for directory, children, files in os.walk(folder):
        children[:] = [name for name in children if name not in {"target", ".git", "__pycache__"}]
        build_inputs.extend(Path(directory) / name for name in files
                            if Path(name).suffix in {".rs", ".toml", ".lock"})
fingerprint = hashlib.sha256()
for path in sorted(set(build_inputs)):
    if path.is_file():
        stat = path.stat()
        fingerprint.update(f"{path}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}\n".encode())
stat = native_path.stat()
current = {"source_signature": fingerprint.hexdigest(),
           "binary": [str(native_path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]}
receipt = repo_root / ".artifacts/runtime-receipts/traderesearch-runtime-receipt.json"
if mode == "record":
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(json.dumps(current))
    os.replace(temporary, receipt)
else:
    try:
        previous = json.loads(receipt.read_text())
    except (OSError, ValueError):
        previous = None
    if previous != current:
        print("needs-build")
        raise SystemExit(0)
print(f"ready: NautilusTrader {expected_version}: {native_path}")
' "${EXPECTED_VERSION}" "${PYTHON_SOURCE}" "${1:-check}")"
  [[ "${state}" == ready:* ]]
}

enforce_host_cache_budget() {
  [[ -d "$HOST_TARGET" ]] || return 0
  local used_kb limit_gb
  used_kb="$(du -sk "$HOST_TARGET" | awk '{print $1}')"
  limit_gb="${NAUTILUS_HOST_CACHE_MAX_GB:-4}"
  [[ "$limit_gb" =~ ^[1-9][0-9]*$ ]] || { echo "invalid host Cargo cache budget" >&2; return 2; }
  if (( used_kb > limit_gb * 1024 * 1024 )); then
    if [[ "$HOST_TARGET" == "$ROOT_DIR/.artifacts/nautilus-build/host-target" ]]; then
      cargo clean --manifest-path "$COMPOSITION_ROOT/Cargo.toml" --target-dir "$HOST_TARGET"
      echo "host Cargo cache evicted: exceeded ${limit_gb}GiB; installed extension and receipt retained"
    else
      echo "external Cargo cache exceeds budget; left untouched: $HOST_TARGET" >&2
    fi
  fi
}

if runtime_is_ready; then
  enforce_host_cache_budget
  echo "NautilusTrader extension is already built from the pinned vendor source."
  exit 0
fi

if ! conda run -n "${ENV_NAME}" maturin --version >/dev/null 2>&1; then
  echo "maturin is missing from ${ENV_NAME}; update it with: conda env update -n ${ENV_NAME} -f environment.yml" >&2
  exit 1
fi

echo "Building vendored NautilusTrader ${EXPECTED_VERSION} in ${ENV_NAME} (dev profile, opt=${DEV_OPT_LEVEL}, ${BUILD_JOBS} jobs)."
echo "Cargo artifacts are reused from ${HOST_TARGET}."
cd "${NAUTILUS_ROOT}"
CARGO_BUILD_JOBS="${BUILD_JOBS}" \
CARGO_PROFILE_DEV_OPT_LEVEL="${DEV_OPT_LEVEL}" \
CARGO_TARGET_DIR="${HOST_TARGET}" \
  conda run --no-capture-output -n "${ENV_NAME}" maturin develop --profile dev --locked --manifest-path "${COMPOSITION_ROOT}/Cargo.toml"

runtime_is_ready record || {
  echo "NautilusTrader build completed, but the pinned native extension did not load from the vendor source." >&2
  exit 1
}

enforce_host_cache_budget

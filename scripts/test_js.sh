#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if (($# == 0)); then
  set -- tests/js
fi

ENV_NAME="${FT_ENV_NAME:-GTHT}"
# The repository pins Python Playwright in GTHT. Reuse its version-matched Node
# driver and JS API instead of the host's unrelated Node module search path.
PLAYWRIGHT_PACKAGE="$(conda run --no-capture-output -n "${ENV_NAME}" python -c 'from pathlib import Path; import playwright; print(Path(playwright.__file__).parent / "driver" / "package")')"
PLAYWRIGHT_NODE="$(conda run --no-capture-output -n "${ENV_NAME}" python -c 'from playwright._impl._driver import compute_driver_executable; print(compute_driver_executable()[0])')"
if [[ ! -f "${PLAYWRIGHT_PACKAGE}/package.json" || ! -x "${PLAYWRIGHT_NODE}" ]]; then
  echo "[test-js] Playwright runtime unavailable in Conda env ${ENV_NAME}" >&2
  exit 2
fi

NODE_MODULE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/factortester-playwright.XXXXXX")"
trap 'rm -rf "${NODE_MODULE_ROOT}"' EXIT
mkdir -p "${NODE_MODULE_ROOT}/node_modules"
ln -s "${PLAYWRIGHT_PACKAGE}" "${NODE_MODULE_ROOT}/node_modules/playwright"

run_node() {
  NODE_PATH="${NODE_MODULE_ROOT}/node_modules${NODE_PATH:+:${NODE_PATH}}" \
    conda run --no-capture-output -n "${ENV_NAME}" "${PLAYWRIGHT_NODE}" "$@"
}

for target in "$@"; do
  if [[ "${target}" == "tests/js" ]]; then
    for file in tests/js/test_*.js; do
      if [[ "${file}" == "tests/js/test_math_latex_safe.js" ]]; then
        echo "[test-js] pytest fixture wrapper for ${file}"
        "${ROOT_DIR}/scripts/test.sh" tests/scripts/test_math_latex_safe_js.py
      else
        echo "[test-js] playwright node ${file} (env=${ENV_NAME})"
        run_node "${file}"
      fi
    done
  elif [[ "${target}" == tests/js/test_*.js && -f "${target}" ]]; then
    if [[ "${target}" == "tests/js/test_math_latex_safe.js" ]]; then
      echo "[test-js] pytest fixture wrapper for ${target}"
      "${ROOT_DIR}/scripts/test.sh" tests/scripts/test_math_latex_safe_js.py
    else
      echo "[test-js] playwright node ${target} (env=${ENV_NAME})"
      run_node "${target}"
    fi
  else
    echo "[test-js] Invalid JS test target: ${target}" >&2
    exit 2
  fi
done

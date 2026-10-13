#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if (($# == 0)); then
  set -- tests/js
fi

for target in "$@"; do
  if [[ "${target}" == "tests/js" ]]; then
    for file in tests/js/test_*.js; do
      if [[ "${file}" == "tests/js/test_math_latex_safe.js" ]]; then
        echo "[test-js] pytest fixture wrapper for ${file}"
        "${ROOT_DIR}/scripts/test.sh" tests/scripts/test_math_latex_safe_js.py
      else
        echo "[test-js] node ${file}"
        node "${file}"
      fi
    done
  elif [[ "${target}" == tests/js/test_*.js && -f "${target}" ]]; then
    if [[ "${target}" == "tests/js/test_math_latex_safe.js" ]]; then
      echo "[test-js] pytest fixture wrapper for ${target}"
      "${ROOT_DIR}/scripts/test.sh" tests/scripts/test_math_latex_safe_js.py
    else
      echo "[test-js] node ${target}"
      node "${target}"
    fi
  else
    echo "[test-js] Invalid JS test target: ${target}" >&2
    exit 2
  fi
done

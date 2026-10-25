#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# Git hooks export repository-local variables. Tests create temporary Git
# repositories; inheriting these variables redirects their writes here.
while IFS= read -r git_env; do
  unset "${git_env}"
done < <(git rev-parse --local-env-vars)

ENV_NAME="${FT_ENV_NAME:-GTHT}"

echo "[test] env=${ENV_NAME}"
# Fail before threaded tests can hang in SQLite's known Unix mutex inversion.
conda run -n "${ENV_NAME}" python -c 'import sqlite3; import sys; sys.exit("SQLite 3.51.0/3.51.1 存在 Unix 并发死锁，请按 environment.yml 更新 GTHT" if sqlite3.sqlite_version_info in {(3, 51, 0), (3, 51, 1)} else 0)'

needs_nautilus=0
if (($# == 0)); then
  needs_nautilus=1
else
  for target in "$@"; do
    target="${target%%::*}"
    target="${target#./}"
    if [[ "${target}" == "${ROOT_DIR}/"* ]]; then
      target="${target#"${ROOT_DIR}/"}"
    fi
    if [[ "${target}" == "tests/server/test_nautilus_bridge_reports.py" || \
          "${target}" == "tests/server/test_nautilus_bridge_version.py" ]]; then
      continue
    fi
    case "${target}" in
      tests/scripts/test_nautilus_extension_build.py)
        needs_nautilus=1
        break
        ;;
      tests|tests/)
        needs_nautilus=1
        break
        ;;
      tests/server|tests/server/|tests/server/test_nautilus_bridge_*.py|tests/benchmarks/bench_nautilus_*.py)
        needs_nautilus=1
        break
        ;;
    esac
  done
fi
if ((needs_nautilus)); then
  echo "[test] ensuring the vendored NautilusTrader extension is built"
  FT_ENV_NAME="${ENV_NAME}" "${ROOT_DIR}/scripts/build_nautilus_extension.sh"
fi

echo "[test] cmd=python -m pytest -q ${*:-<full suite>}"

conda run --no-capture-output -n "${ENV_NAME}" python -m pytest -q "$@"

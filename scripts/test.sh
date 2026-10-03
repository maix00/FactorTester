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
echo "[test] cmd=python -m pytest -q"

conda run --no-capture-output -n "${ENV_NAME}" python -m pytest -q

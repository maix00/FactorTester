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

echo "[test] checking generated Skill copies"
python3 tools/cli/agent-harness/scripts/sync_skill.py --check

echo "[test] env=${ENV_NAME}"
echo "[test] cmd=python -m pytest -q"

conda run -n "${ENV_NAME}" python -m pytest -q

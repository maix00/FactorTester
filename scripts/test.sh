#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

ENV_NAME="${FT_ENV_NAME:-GTHT}"

echo "[test] checking generated Skill copies"
python3 tools/cli/agent-harness/scripts/sync_skill.py --check

echo "[test] env=${ENV_NAME}"
echo "[test] cmd=python -m pytest -q"

conda run -n "${ENV_NAME}" python -m pytest -q

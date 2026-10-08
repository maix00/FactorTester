#!/usr/bin/env bash
set -euo pipefail

# Install the FactorTester CLI wheel into a pipx-managed environment.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT_SPEC="${1:-$ROOT_DIR/tools/cli}"
PIPX_BIN="${PIPX_BIN:-pipx}"

if ! command -v "$PIPX_BIN" >/dev/null 2>&1; then
  echo "pipx is required; install it with: brew install pipx" >&2
  exit 1
fi

"$PIPX_BIN" install --force "$CLIENT_SPEC"

echo "Installed FactorTester CLI entrypoints:"
echo "  factortester"
echo "  factortester-manager"

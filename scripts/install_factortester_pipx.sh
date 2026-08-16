#!/usr/bin/env bash
set -euo pipefail

# Install the two FactorTester CLI wheels into one pipx-managed environment.
# The client wheel is the owner of the environment; the Research Harness wheel
# is injected without dependency resolution because it is already paired with
# the exact client version in this release.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT_SPEC="${1:-$ROOT_DIR/tools/cli}"
HARNESS_SPEC="${2:-$ROOT_DIR/tools/cli/agent-harness}"
PIPX_BIN="${PIPX_BIN:-pipx}"

if ! command -v "$PIPX_BIN" >/dev/null 2>&1; then
  echo "pipx is required; install it with: brew install pipx" >&2
  exit 1
fi

"$PIPX_BIN" install --force "$CLIENT_SPEC"
"$PIPX_BIN" inject \
  --force \
  --include-apps \
  --pip-args="--no-deps" \
  factortester "$HARNESS_SPEC"

echo "Installed FactorTester CLI entrypoints:"
echo "  factortester"
echo "  factortester-manager"
echo "  cli-anything-factortester-research"

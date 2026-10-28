#!/usr/bin/env bash
# Stable public entrypoint; the cache-aware implementation has one owner.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec bash "$ROOT/scripts/server/native_wheel_build.sh" "$@"

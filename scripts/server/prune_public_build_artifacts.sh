#!/usr/bin/env bash
# Reclaim only disposable Docker build state.  Never remove a tagged rollback
# image or a running service image.
set -Eeuo pipefail
keep="${FACTORTESTER_BUILD_CACHE_KEEP:-5GB}"
if command -v docker >/dev/null 2>&1; then
  docker image prune -f >/dev/null || true
  docker builder prune -f --keep-storage "$keep" >/dev/null || true
fi
df -h / /data 2>/dev/null || df -h /

#!/usr/bin/env bash
set -Eeuo pipefail

minimum_gb="${FACTORTESTER_MIN_BUILD_FREE_GB:-20}"
available_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
available_gb="$((available_kb / 1024 / 1024))"
if (( available_gb < minimum_gb )); then
  echo "refusing to build: root filesystem has ${available_gb}G free, need ${minimum_gb}G" >&2
  echo "clean Docker build cache/images or use an external builder before retrying" >&2
  exit 3
fi

if [[ -r /proc/meminfo ]]; then
  available_mb="$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)"
  if (( available_mb < 2048 )); then
    echo "refusing to build: MemAvailable=${available_mb}MB, need 2048MB" >&2
    exit 3
  fi
fi

if command -v docker >/dev/null 2>&1; then
  if ! docker info >/dev/null 2>&1; then
    echo "refusing to build: Docker daemon is unhealthy" >&2
    exit 3
  fi
fi

echo "build capacity ok: free=${available_gb}G minimum=${minimum_gb}G"

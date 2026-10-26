#!/usr/bin/env bash
# Guard local Nautilus/py-alpha builds. Rust target directories have reached
# ~100 GiB; a successful build must not consume the last free space.
set -Eeuo pipefail

minimum_gb="${FACTORTESTER_MIN_LOCAL_BUILD_FREE_GB:-40}"
minimum_mem_mb="${FACTORTESTER_MIN_LOCAL_BUILD_MEM_MB:-6144}"
root="${FACTORTESTER_BUILD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

free_kb="$(df -Pk "$root" | awk 'NR==2 {print $4}')"
free_gb="$((free_kb / 1024 / 1024))"
if (( free_gb < minimum_gb )); then
  echo "refusing local build: ${root} has ${free_gb}G free, need ${minimum_gb}G" >&2
  echo "remove stale Rust target directories or set a larger build volume" >&2
  exit 3
fi

if [[ -r /proc/meminfo ]]; then
  mem_mb="$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)"
  if (( mem_mb < minimum_mem_mb )); then
    echo "refusing local build: MemAvailable=${mem_mb}MB, need ${minimum_mem_mb}MB" >&2
    exit 3
  fi
fi

echo "local build capacity ok: free=${free_gb}G minimum=${minimum_gb}G"

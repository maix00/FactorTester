#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  printf '%s\n' \
    "Usage: ./scripts/push_main_to_server.sh [--start]" \
    "" \
    "Compatibility entrypoint for synchronous public-container publication." \
    "Publication always pushes main, activates the new application image," \
    "restores fixed service 8000, verifies health, and rolls back on failure." \
    "The legacy --start option is accepted but no longer changes behavior."
}

for argument in "$@"; do
  case "$argument" in
    --start)
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'unknown or retired argument: %s\n' "$argument" >&2
      usage >&2
      exit 2
      ;;
  esac
done

"$repo_root/scripts/server/publish_public_main.sh"
exec "$repo_root/scripts/server/sync_public_field_history.sh"

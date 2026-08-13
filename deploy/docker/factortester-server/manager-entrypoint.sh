#!/bin/sh
set -eu

is_enabled() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

if ! is_enabled "${FACTORTESTER_HOT_RELOAD:-0}"; then
    exec "$@"
fi

repo_root="${FACTORTESTER_REPO_ROOT:?set FACTORTESTER_REPO_ROOT when hot reload is enabled}"
if [ ! -d "$repo_root" ]; then
    echo "Hot-reload source directory is missing: $repo_root" >&2
    exit 1
fi

echo "FactorTester development hot reload enabled for $repo_root (*.py)"
exec watchmedo auto-restart \
    --directory "$repo_root" \
    --patterns '*.py' \
    --ignore-patterns '*/.git/*;*/__pycache__/*;*.pyc' \
    --recursive \
    --signal SIGTERM \
    --kill-after 20 \
    --debounce-interval 0.5 \
    --no-restart-on-command-exit \
    -- "$@"

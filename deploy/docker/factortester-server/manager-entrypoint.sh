#!/bin/sh
set -eu

is_enabled() {
    case "${1:-}" in
        1|true|TRUE|yes|YES|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

start_manager() {
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
        -- "$@"
}

if ! is_enabled "${FACTORTESTER_START_FIXED_SERVICE:-0}"; then
    exec "$@"
fi

state_root="${FACTORTESTER_STATE_ROOT:?set FACTORTESTER_STATE_ROOT when the fixed service is enabled}"
fixed_port="${FACTORTESTER_FIXED_PORT:-7999}"
fixed_branch="${FACTORTESTER_FIXED_BRANCH:-feat}"
fixed_timeout="${FACTORTESTER_FIXED_STARTUP_TIMEOUT:-180}"
capability_file="${FACTORTESTER_FIXED_CAPABILITY_FILE:-$state_root/manager-capability.key}"
manager_endpoint="${FACTORTESTER_FIXED_MANAGER_ENDPOINT:-http://127.0.0.1:7998}"

start_manager "$@" &
manager_pid=$!

cleanup() {
    kill "$manager_pid" 2>/dev/null || true
}
trap cleanup INT TERM HUP

python /usr/local/bin/start-fixed-service \
    --manager "$manager_endpoint" \
    --capability-file "$capability_file" \
    --branch "$fixed_branch" \
    --port "$fixed_port" \
    --timeout "$fixed_timeout" || {
        cleanup
        wait "$manager_pid" 2>/dev/null || true
        exit 1
    }

wait "$manager_pid"

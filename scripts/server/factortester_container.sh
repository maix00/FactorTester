#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
compose_file="$repo_root/deploy/docker/factortester-server/compose.yaml"
env_file="${FACTORTESTER_DOCKER_ENV_FILE:-$HOME/Library/Application Support/FactorTester/server-docker/server.env}"

usage() {
  cat <<'EOF'
Usage: scripts/server/factortester_container.sh COMMAND [ARGS...]

Commands:
  config       Render and validate the resolved Compose configuration
  build        Build the WireGuard and FactorTester images
  up           Start the complete server stack from existing images
  down         Stop the complete server stack
  restart      Reconcile and restart the complete server stack
  status       Show container and health status
  logs         Follow logs (additional docker compose log arguments accepted)
  port         Show the host mappings for container ports 7998 and 7997

Set FACTORTESTER_DOCKER_ENV_FILE to use a different deployment environment.
EOF
}

if [[ ! -f "$env_file" ]]; then
  echo "Missing deployment environment: $env_file" >&2
  echo "Start from deploy/docker/factortester-server/server.env.example" >&2
  exit 1
fi

compose=(docker compose --env-file "$env_file" --file "$compose_file")
command="${1:-}"
if [[ -z "$command" ]]; then
  usage
  exit 2
fi
shift

case "$command" in
  config)
    "${compose[@]}" config "$@"
    ;;
  build)
    "${compose[@]}" build "$@"
    ;;
  up)
    "${compose[@]}" up --detach --no-build --remove-orphans --wait "$@"
    ;;
  down)
    "${compose[@]}" down --remove-orphans "$@"
    ;;
  restart)
    "${compose[@]}" up --detach --no-build --remove-orphans --force-recreate --wait "$@"
    ;;
  status)
    "${compose[@]}" ps "$@"
    ;;
  logs)
    "${compose[@]}" logs --follow "$@"
    ;;
  port)
    "${compose[@]}" port wireguard 7998
    "${compose[@]}" port wireguard 7997
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac

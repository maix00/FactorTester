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
  stack-restart Restart the complete stack without rebuilding images
  manager-reload Restart the Manager container without recreating it
  manager-restart Recreate only the Manager container without rebuilding images
  hot-reload-status Verify the local Python source watcher is enabled
  service-start PORT Start the Manager-owned service at PORT
  service-stop PORT Stop the Manager-owned service at PORT
  service-reload PORT Restart only the service API at PORT
  service-restart PORT Restart the full service bundle at PORT
  service-force-stop PORT Force-stop the Manager-owned service at PORT
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
manager_helper="$repo_root/scripts/server/local_manager_service.py"

env_value() {
  local key="$1"
  local line=""
  line="$(sed -n -e "s/^${key}=//p" "$env_file" | tail -n 1)"
  printf '%s' "$line"
}

deployment_value() {
  local key="$1"
  local fallback="$2"
  if [[ -n "${!key:-}" ]]; then
    printf '%s' "${!key}"
    return
  fi
  local value
  value="$(env_value "$key")"
  printf '%s' "${value:-$fallback}"
}

manager_service_action() {
  local action="$1"
  local port="$2"
  [[ "$port" =~ ^[0-9]+$ ]] && ((port >= 1 && port <= 65535)) || {
    echo "Service port must be an integer between 1 and 65535: $port" >&2
    exit 2
  }
  [[ -f "$manager_helper" ]] || {
    echo "Missing Manager service helper: $manager_helper" >&2
    exit 1
  }
  local state_root capability_file manager_port manager_endpoint python_bin timeout
  state_root="$(deployment_value FACTORTESTER_STATE_ROOT "")"
  [[ -n "$state_root" ]] || {
    echo "FACTORTESTER_STATE_ROOT is required for Manager service control" >&2
    exit 1
  }
  capability_file="$(deployment_value FACTORTESTER_FIXED_CAPABILITY_FILE "$state_root/manager-capability.key")"
  manager_port="$(deployment_value FACTORTESTER_MANAGER_HOST_PORT 7998)"
  manager_endpoint="$(deployment_value FACTORTESTER_LOCAL_MANAGER_ENDPOINT "http://127.0.0.1:${manager_port}")"
  python_bin="${FACTORTESTER_MAINTENANCE_PYTHON:-python3}"
  timeout="${FACTORTESTER_SERVICE_ACTION_TIMEOUT:-120}"
  exec "$python_bin" "$manager_helper" \
    --manager "$manager_endpoint" \
    --capability-file "$capability_file" \
    --port "$port" \
    --action "$action" \
    --timeout "$timeout"
}

manager_restart() {
  local recreate="$1"
  if [[ "$recreate" == "1" ]]; then
    "${compose[@]}" up --detach --no-build --remove-orphans \
      --force-recreate --wait manager
  else
    if [[ -n "$("${compose[@]}" ps -q manager)" ]]; then
      "${compose[@]}" restart manager
    else
      "${compose[@]}" up --detach --no-build --remove-orphans manager
    fi
    "${compose[@]}" up --detach --no-build --remove-orphans --wait manager
  fi
}

manager_hot_reload_status() {
  local configured
  configured="$(deployment_value FACTORTESTER_HOT_RELOAD 1)"
  case "$configured" in
    1|true|TRUE|yes|YES|on|ON)
      echo "FACTORTESTER_HOT_RELOAD=$configured (enabled)"
      "${compose[@]}" ps manager
      ;;
    *)
      echo "FACTORTESTER_HOT_RELOAD=$configured (disabled)" >&2
      return 1
      ;;
  esac
}

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
  stack-restart)
    "${compose[@]}" up --detach --no-build --remove-orphans --force-recreate --wait "$@"
    ;;
  manager-reload)
    [[ "$#" -eq 0 ]] || { echo "Usage: $0 manager-reload" >&2; exit 2; }
    manager_restart 0
    ;;
  manager-restart)
    [[ "$#" -eq 0 ]] || { echo "Usage: $0 manager-restart" >&2; exit 2; }
    manager_restart 1
    ;;
  hot-reload-status)
    [[ "$#" -eq 0 ]] || { echo "Usage: $0 hot-reload-status" >&2; exit 2; }
    manager_hot_reload_status
    ;;
  service-start)
    [[ "$#" -eq 1 ]] || { echo "Usage: $0 service-start PORT" >&2; exit 2; }
    manager_service_action start "$1"
    ;;
  service-stop)
    [[ "$#" -eq 1 ]] || { echo "Usage: $0 service-stop PORT" >&2; exit 2; }
    manager_service_action stop "$1"
    ;;
  service-reload)
    [[ "$#" -eq 1 ]] || { echo "Usage: $0 service-reload PORT" >&2; exit 2; }
    manager_service_action reload-api "$1"
    ;;
  service-restart)
    [[ "$#" -eq 1 ]] || { echo "Usage: $0 service-restart PORT" >&2; exit 2; }
    manager_service_action restart-bundle "$1"
    ;;
  service-force-stop)
    [[ "$#" -eq 1 ]] || { echo "Usage: $0 service-force-stop PORT" >&2; exit 2; }
    manager_service_action force-stop "$1"
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

#!/usr/bin/env bash
set -Eeuo pipefail

# Manage one FactorTester service port without restarting the public Manager.
# The Manager remains the only control plane; service sources are stable
# symlinks into /opt/factortester-container/releases.

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="${FACTORTESTER_PUBLIC_DOCKER_ENV_FILE:-/etc/factortester-container/public.env}"
[[ -f "$env_file" ]] || { echo "Missing $env_file" >&2; exit 2; }
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

git_root="${FACTORTESTER_REMOTE_GIT_ROOT:-/opt/factortester}"
container_root="${FACTORTESTER_REMOTE_CONTAINER_ROOT:-/opt/factortester-container}"
services_root="$container_root/services"
releases_root="$container_root/releases"
capability_file="$container_root/state/manager-capability.key"
manager_url="${FACTORTESTER_MANAGER_LOCAL_URL:-https://127.0.0.1:7998}"

usage() {
  cat <<'EOF'
Usage: manage_public_service.sh COMMAND [ARGS...]

Commands:
  status
  set-version PORT SHA   point PORT at a release worktree and restart it
  restart PORT
EOF
}

manager_json() {
  local method="$1" path="$2" form="${3:-}"
  python3 - "$manager_url" "$capability_file" "$method" "$path" "$form" <<'PY'
import json, ssl, sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
base, capability, method, path, form = sys.argv[1:6]
token = Path(capability).read_text(encoding="ascii").strip()
data = urlencode({"instance_id": form}).encode() if form else None
req = Request(base.rstrip("/") + path, data=data, method=method, headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/x-www-form-urlencoded",
})
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
with urlopen(req, timeout=15, context=ctx) as response:
    raw = response.read()
print(raw.decode("utf-8"))
PY
}

service_instance() {
  local port="$1"
  manager_json GET /api/worktrees | python3 -c '
import json,sys
port=int(sys.argv[1])
for item in json.load(sys.stdin).get("worktrees", []):
    if int(item.get("port") or 0)==port:
        print(item["instance_id"], "online" if item.get("online") else "offline")
        break
else:
    raise SystemExit(f"port {port} is not registered")
' "$port"
}

status() {
  manager_json GET /api/worktrees | python3 -c '
import json,sys
for item in json.load(sys.stdin).get("worktrees", []):
    print(f"{item.get(\"port\")}\t{item.get(\"branch\")}\t{item.get(\"head\")}\t{item.get(\"instance_id\")}\tonline={bool(item.get(\"online\"))}")
'
}

restart_port() {
  local port="$1" instance state
  read -r instance state < <(service_instance "$port")
  if [[ "$state" == "online" ]]; then
    manager_json POST /restart-bundle "$instance" >/dev/null
  else
    manager_json POST /start "$instance" >/dev/null
  fi
  echo "service $port restarted ($instance)"
}

set_version() {
  local port="$1" revision="$2"
  [[ "$port" =~ ^[1-9][0-9]*$ ]] || { echo "invalid port" >&2; exit 2; }
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "revision must be a full SHA" >&2; exit 2; }
  local release="$releases_root/$revision"
  [[ -d "$release" ]] || {
    sudo git --git-dir="$git_root/repo.git" worktree add --detach "$release" "$revision" >/dev/null
  }
  [[ "$(sudo git -C "$release" rev-parse HEAD)" == "$revision" ]]
  sudo install -d -m 0755 "$services_root"
  sudo ln -sfn "../releases/$revision" "$services_root/$port"
  restart_port "$port"
}

case "${1:-status}" in
  status) status ;;
  restart) restart_port "${2:?port required}" ;;
  set-version) set_version "${2:?port required}" "${3:?revision required}" ;;
  -h|--help|help) usage ;;
  *) usage >&2; exit 2 ;;
esac

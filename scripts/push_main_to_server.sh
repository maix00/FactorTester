#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${FACTORTESTER_REMOTE:-launch-advisor}"
REMOTE_ROOT="${FACTORTESTER_REMOTE_ROOT:-/opt/factortester}"
START_SERVICES=0
UPDATE_SETTINGS="${FACTORTESTER_UPDATE_SETTINGS:-0}"

SERVICE_DIR="$ROOT_DIR/deploy"
REQUIREMENTS_FILE="$SERVICE_DIR/requirements-linux.txt"
SETTINGS_FILE="$SERVICE_DIR/remote.settings.json"
REMOTE_SETTINGS_FILE="$REMOTE_ROOT/releases/.settings"
REMOTE_STATE_DIR="$REMOTE_ROOT/manager-state"
REMOTE_TMP_SUFFIX=""

usage() {
  cat <<'EOF'
Usage: ./scripts/push_main_to_server.sh [--start]

Default: push main incrementally, install/update the Linux runtime, materialize
the release, and install the split Manager/API/daemon units without starting
FactorTester.

--start  start 7998 Manager (which owns 7997), then ask Manager to start 8000
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)
      START_SERVICES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$REMOTE_ROOT" != "/opt/factortester" ]]; then
  echo "FACTORTESTER_REMOTE_ROOT must remain /opt/factortester for the bundled units" >&2
  exit 2
fi

for required in git ssh scp; do
  command -v "$required" >/dev/null || {
    echo "missing local command: $required" >&2
    exit 2
  }
done

[[ "$(git -C "$ROOT_DIR" branch --show-current)" == "main" ]] || {
  echo "run this script from the main worktree" >&2
  exit 2
}
git -C "$ROOT_DIR" diff --quiet || {
  echo "main has tracked working-tree changes; commit them before deployment" >&2
  exit 2
}
git -C "$ROOT_DIR" diff --cached --quiet || {
  echo "main has staged changes; commit them before deployment" >&2
  exit 2
}

for required_file in \
  "$REQUIREMENTS_FILE" \
  "$SETTINGS_FILE" \
  "$SERVICE_DIR/factortester-main-daemon.service" \
  "$SERVICE_DIR/factortester-main.service" \
  "$SERVICE_DIR/factortester-manager.service"; do
  [[ -f "$required_file" ]] || {
    echo "deployment file is missing: $required_file" >&2
    exit 2
  }
done

REVISION="$(git -C "$ROOT_DIR" rev-parse main)"
RELEASE_DIR="$REMOTE_ROOT/releases/$REVISION"
REMOTE_TMP_SUFFIX="${REVISION:0:12}-$$"
REQUIREMENTS_TMP="/tmp/factortester-requirements-$REMOTE_TMP_SUFFIX.txt"
SETTINGS_TMP="/tmp/factortester-settings-$REMOTE_TMP_SUFFIX.json"
SERVICE_TMP_DIR="/tmp/factortester-services-$REMOTE_TMP_SUFFIX"

remote_exec() {
  ssh -o BatchMode=yes -o ConnectTimeout=20 -o ConnectionAttempts=1 "$REMOTE" "$@"
}

echo "Preparing $REMOTE for incremental main deployment"
remote_exec 'command -v git >/dev/null 2>&1 || { echo "remote git is required" >&2; exit 1; }'
remote_exec "set -eu
  sudo install -d -o ecs-user -g ecs-user '$REMOTE_ROOT'
  install -d '$REMOTE_ROOT/releases' '$REMOTE_STATE_DIR'
  install -d /data/sqlite /data/Factors /data/factor_tester_log /data/job-results /data/sources/LocalCNFutures
  if [ ! -d '$REMOTE_ROOT/repo.git' ]; then
    git init --bare '$REMOTE_ROOT/repo.git' >/dev/null
  fi
"

echo "Pushing main $REVISION to $REMOTE (Git transfers missing objects only)"
GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ConnectionAttempts=1" \
  git -C "$ROOT_DIR" push "$REMOTE:$REMOTE_ROOT/repo.git" "main:refs/heads/main"

REMOTE_REVISION="$(remote_exec "git --git-dir '$REMOTE_ROOT/repo.git' rev-parse refs/heads/main")"
[[ "$REMOTE_REVISION" == "$REVISION" ]] || {
  echo "remote Git revision mismatch: $REMOTE_REVISION != $REVISION" >&2
  exit 1
}

echo "Installing or reusing the Linux runtime"
scp "$REQUIREMENTS_FILE" "$REMOTE:$REQUIREMENTS_TMP"
remote_exec "set -eu
  if ! command -v python3 >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip
  fi
  if [ ! -x '$REMOTE_ROOT/venv/bin/python' ]; then
    python3 -m venv '$REMOTE_ROOT/venv'
  fi
  if [ ! -f '$REMOTE_ROOT/requirements-linux.txt' ] || ! cmp -s '$REQUIREMENTS_TMP' '$REMOTE_ROOT/requirements-linux.txt'; then
    '$REMOTE_ROOT/venv/bin/python' -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip setuptools wheel
    '$REMOTE_ROOT/venv/bin/python' -m pip install --disable-pip-version-check --no-cache-dir -r '$REQUIREMENTS_TMP'
    install -m 0644 '$REQUIREMENTS_TMP' '$REMOTE_ROOT/requirements-linux.txt'
  fi
  rm -f '$REQUIREMENTS_TMP'
"

echo "Preparing persistent data settings and Manager credentials"
scp "$SETTINGS_FILE" "$REMOTE:$SETTINGS_TMP"
CAPABILITY_TOKEN="$(remote_exec "set -eu
  path='$REMOTE_STATE_DIR/manager-capability.key'
  if [ -s \"\$path\" ]; then
    tr -d '\\n' < \"\$path\"
  else
    token=\$(od -An -tx1 -N32 /dev/urandom | tr -d ' \\n')
    umask 077
    printf '%s' \"\$token\" > \"\$path\"
    printf '%s' \"\$token\"
  fi
")"
REGISTRATION_TOKEN="$(remote_exec "set -eu
  path='$REMOTE_STATE_DIR/federation-registration.key'
  if [ -s \"\$path\" ]; then
    tr -d '\\n' < \"\$path\"
  else
    token=\$(od -An -tx1 -N32 /dev/urandom | tr -d ' \\n')
    umask 077
    printf '%s' \"\$token\" > \"\$path\"
    printf '%s' \"\$token\"
  fi
")"
PUBLIC_ENDPOINT="${FACTORTESTER_PUBLIC_ENDPOINT:-}"
remote_exec "set -eu
  umask 077
  printf '%s\\n' \
    'GTHT_MANAGER_CAPABILITY_TOKEN=$CAPABILITY_TOKEN' \
    'FACTORTESTER_FEDERATION_REGISTRATION_TOKEN=$REGISTRATION_TOKEN' > '$REMOTE_STATE_DIR/manager.env'
  if [ -n '$PUBLIC_ENDPOINT' ]; then
    printf '%s\\n' 'FACTORTESTER_MANAGER_PUBLIC_ENDPOINT=$PUBLIC_ENDPOINT' >> '$REMOTE_STATE_DIR/manager.env'
  fi
  chmod 600 '$REMOTE_STATE_DIR/manager.env' '$REMOTE_STATE_DIR/manager-capability.key' '$REMOTE_STATE_DIR/federation-registration.key'
  if [ '$UPDATE_SETTINGS' = 1 ] || [ ! -f '$REMOTE_SETTINGS_FILE' ]; then
    install -m 0640 '$SETTINGS_TMP' '$REMOTE_SETTINGS_FILE'
  fi
  rm -f '$SETTINGS_TMP'
"

echo "Installing systemd units"
remote_exec "set -eu; install -d '$SERVICE_TMP_DIR'"
scp "$SERVICE_DIR/factortester-main-daemon.service" "$SERVICE_DIR/factortester-main.service" "$SERVICE_DIR/factortester-manager.service" "$REMOTE:$SERVICE_TMP_DIR/"
remote_exec "set -eu
  sudo install -o root -g root -m 0644 '$SERVICE_TMP_DIR/factortester-main-daemon.service' /etc/systemd/system/factortester-main-daemon.service
  sudo install -o root -g root -m 0644 '$SERVICE_TMP_DIR/factortester-main.service' /etc/systemd/system/factortester-main.service
  sudo install -o root -g root -m 0644 '$SERVICE_TMP_DIR/factortester-manager.service' /etc/systemd/system/factortester-manager.service
  rm -f '$SERVICE_TMP_DIR/factortester-main-daemon.service' '$SERVICE_TMP_DIR/factortester-main.service' '$SERVICE_TMP_DIR/factortester-manager.service'
  rmdir '$SERVICE_TMP_DIR'
"

PREVIOUS_RELEASE="$(remote_exec "readlink -f '$REMOTE_ROOT/current' 2>/dev/null || true")"
echo "Materializing release $REVISION on the server"
remote_exec "set -eu
  release='$RELEASE_DIR'
  if [ -e \"\$release\" ] && [ ! -e \"\$release/.git\" ]; then
    mv \"\$release\" \"\$release.archive-$REMOTE_TMP_SUFFIX\"
  fi
  if [ ! -e \"\$release/.git\" ]; then
    git --git-dir='$REMOTE_ROOT/repo.git' worktree add --detach \"\$release\" refs/heads/main >/dev/null
  fi
  printf '%s\\n' '$REVISION' > \"\$release/.deployment-revision\"
  next='$REMOTE_ROOT/.current-$REMOTE_TMP_SUFFIX'
  rm -f \"\$next\"
  ln -s '$RELEASE_DIR' \"\$next\"
  mv -Tf \"\$next\" '$REMOTE_ROOT/current'
  sudo systemctl daemon-reload
"

remote_exec "printf '%s\\t%s\\t%s\\t%s\\t%s\\n' '$(date -u +%Y-%m-%dT%H:%M:%SZ)' '$REVISION' '$REMOTE_REVISION' '$PREVIOUS_RELEASE' 'prepared-not-started' >> '$REMOTE_ROOT/deployments.log'"

if [[ "$START_SERVICES" != 1 ]]; then
  echo "Deployment prepared; 7998, 7997, and 8000 were not started"
  echo "  local main:  $REVISION"
  echo "  remote main: $REMOTE_REVISION"
  echo "  release:     $RELEASE_DIR"
  echo "  registration token for the peer Manager: $REGISTRATION_TOKEN"
  exit 0
fi

echo "Starting the 7998 Manager and its 7997 artifact data plane"
remote_exec "set -eu
  sudo systemctl disable --now factortester.service 2>/dev/null || true
  # 8000 is deliberately not started by systemd here.  The Manager owns the
  # fixed service lifecycle so it can advertise the service only after its
  # 7997 data plane is ready.
  sudo systemctl disable --now factortester-main.service factortester-main-daemon.service 2>/dev/null || true
  sudo systemctl enable factortester-manager.service >/dev/null
  sudo systemctl restart factortester-manager.service
  manager_ready=0
  for attempt in \$(seq 1 30); do
    if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:7998/ >/dev/null; then
      manager_ready=1
      break
    fi
    sleep 1
  done
  test "\$manager_ready" = 1
  artifact_ready=0
  for attempt in \$(seq 1 30); do
    if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:7997/healthz >/dev/null; then
      artifact_ready=1
      break
    fi
    sleep 1
  done
  test "\$artifact_ready" = 1
  manager_token=\$(sudo cat '$REMOTE_STATE_DIR/manager-capability.key')
  worktrees=\$(curl --fail --silent --show-error --max-time 20 \\
    -H \"Authorization: Bearer \$manager_token\" \\
    http://127.0.0.1:7998/api/worktrees)
  fixed_instance_id=\$(printf '%s' "\$worktrees" | '$REMOTE_ROOT/venv/bin/python' -c '
import json, sys
payload = json.load(sys.stdin)
for item in payload.get(\"worktrees\", []):
    if int(item.get(\"port\") or 0) == 8000:
        print(item.get(\"instance_id\") or \"\")
        break
')
  test -n "\$fixed_instance_id"
  echo \"Starting fixed 8000 through Manager instance \$fixed_instance_id\"
  curl --fail --silent --show-error --max-time 30 \\
    -X POST -H \"Authorization: Bearer \$manager_token\" \\
    --data-urlencode "instance_id=\$fixed_instance_id" \\
    http://127.0.0.1:7998/start >/dev/null
  curl --fail --silent --show-error --max-time 30 http://127.0.0.1:8000/ >/dev/null
  printf '%s\\t%s\\t%s\\t%s\\t%s\\n' '$(date -u +%Y-%m-%dT%H:%M:%SZ)' '$REVISION' '$REMOTE_REVISION' '$PREVIOUS_RELEASE' 'healthy' >> '$REMOTE_ROOT/deployments.log'
"

echo "Deployment healthy"
echo "  local main:  $REVISION"
echo "  remote main: $REMOTE_REVISION"
echo "  Manager:     http://$REMOTE:7998/"
echo "  service:     http://$REMOTE:8000/"

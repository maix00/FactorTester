#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
remote="${FACTORTESTER_REMOTE:-launch-advisor}"
remote_container_root="${FACTORTESTER_REMOTE_CONTAINER_ROOT:-/opt/factortester-container}"
remote_env="${FACTORTESTER_REMOTE_PUBLIC_ENV:-/etc/factortester-container/public.env}"
temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/factortester-field-history.XXXXXX")"
snapshot="$temporary_root/field-history.sqlite"
compressed_snapshot="$snapshot.gz"
remote_snapshot="/tmp/factortester-field-history-$$.sqlite.gz"

cleanup() {
  rm -rf "$temporary_root"
  "${ssh_command[@]}" "$remote" "rm -f '$remote_snapshot'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ssh_command=(
  ssh
  -o BatchMode=yes
  -o ConnectTimeout="${FACTORTESTER_SSH_CONNECT_TIMEOUT:-20}"
  -o ConnectionAttempts=1
  -o StrictHostKeyChecking=yes
)
if [[ -n "${FACTORTESTER_SSH_PORT:-}" ]]; then
  ssh_command+=(-p "$FACTORTESTER_SSH_PORT")
fi
if [[ -n "${FACTORTESTER_SSH_KEY:-}" ]]; then
  ssh_command+=(-i "$FACTORTESTER_SSH_KEY" -o IdentitiesOnly=yes)
fi
if [[ -n "${FACTORTESTER_SSH_HOST_KEY_ALIAS:-}" ]]; then
  ssh_command+=(-o "HostKeyAlias=$FACTORTESTER_SSH_HOST_KEY_ALIAS")
fi

source_db="$(cd "$repo_root" && python -c 'from settings import CACHE_DB_PATH; print(CACHE_DB_PATH)')"
python "$repo_root/tools/migrations/sync_field_history_snapshot.py" \
  export "$source_db" "$snapshot"
gzip -c "$snapshot" > "$compressed_snapshot"

"${ssh_command[@]}" "$remote" \
  "umask 077; tee '$remote_snapshot' >/dev/null" < "$compressed_snapshot"
"${ssh_command[@]}" "$remote" bash -s -- \
  "$remote_snapshot" "$remote_container_root" "$remote_env" <<'REMOTE'
set -Eeuo pipefail

snapshot="$1"
container_root="$2"
production_env="$3"
expanded_snapshot="${snapshot%.gz}"
revision="$(sudo sed -n 's/^FACTORTESTER_REVISION=//p' "$production_env" | head -n 1)"
release_root="$container_root/releases"
public_script="$release_root/$revision/scripts/server/factortester_public_container.sh"
container="$({
  sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
    bash "$public_script" container-id factortester-public
} | tr -d '\r\n')"
[[ -n "$container" ]]
container_snapshot="/tmp/field-history-sync.sqlite"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
container_backup="/data/backups/field-history/unifieddata-before-$stamp.sqlite"

cleanup_remote() {
  sudo docker exec "$container" rm -f "$container_snapshot" >/dev/null 2>&1 || true
  rm -f "$snapshot" "$expanded_snapshot"
}
trap cleanup_remote EXIT

gzip -dc "$snapshot" > "$expanded_snapshot"
sudo docker cp "$expanded_snapshot" "$container:$container_snapshot"
sudo docker exec "$container" mkdir -p /data/backups/field-history
sudo docker exec "$container" sh -c '
destination="$(python -c '\''from settings import CACHE_DB_PATH; print(CACHE_DB_PATH)'\'')"
python tools/migrations/sync_field_history_snapshot.py \
  install "$1" "$destination" "$2"
python tools/migrations/sync_field_history_snapshot.py \
  install "$1" "$destination" "$2" --apply
' sh "$container_snapshot" "$container_backup"
REMOTE

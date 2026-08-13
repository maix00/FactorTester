#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
deploy_user="${FACTORTESTER_PUBLIC_DEPLOY_USER:-${SUDO_USER:-$(id -un)}}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --deploy-user)
      deploy_user="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown automatic update installer argument: $1" >&2
      exit 2
      ;;
  esac
done
[[ -n "$deploy_user" ]] && id "$deploy_user" >/dev/null
deploy_group="$(id -gn "$deploy_user")"

bin_root="${FACTORTESTER_PUBLIC_BIN_ROOT:-/opt/factortester-container/bin}"
unit_root="${FACTORTESTER_SYSTEMD_UNIT_ROOT:-/etc/systemd/system}"
git_root="${FACTORTESTER_REMOTE_GIT_ROOT:-/opt/factortester}"
[[ "$bin_root" == /* && "$git_root" == /* ]] || {
  echo "automatic update roots must be absolute paths" >&2
  exit 2
}
[[ "$bin_root" != *"|"* && "$git_root" != *"|"* ]] || {
  echo "automatic update roots cannot contain |" >&2
  exit 2
}
service_template="$repo_root/deploy/systemd/factortester-public-update.service.in"
timer_source="$repo_root/deploy/systemd/factortester-public-update.timer"
updater_source="$repo_root/scripts/server/auto_update_public_main.sh"
rendered_service="$(mktemp)"
cleanup() {
  rm -f "$rendered_service"
}
trap cleanup EXIT

sed \
  -e "s/@DEPLOY_USER@/$deploy_user/g" \
  -e "s/@DEPLOY_GROUP@/$deploy_group/g" \
  -e "s|@BIN_ROOT@|$bin_root|g" \
  -e "s|@GIT_ROOT@|$git_root|g" \
  "$service_template" > "$rendered_service"

sudo install -d -m 0755 "$bin_root"
sudo install -m 0755 \
  "$updater_source" "$bin_root/auto_update_public_main.sh"
sudo install -m 0644 \
  "$rendered_service" "$unit_root/factortester-public-update.service"
sudo install -m 0644 \
  "$timer_source" "$unit_root/factortester-public-update.timer"
sudo systemctl daemon-reload
sudo systemctl enable --now factortester-public-update.timer

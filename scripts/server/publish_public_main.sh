#!/usr/bin/env bash
set -Eeuo pipefail

# The caller supplies this only after explicit user release authorization.
[[ "${FACTORTESTER_PUBLISH_AUTHORIZED:-0}" == "1" ]] || {
  echo "explicit release authorization is required (FACTORTESTER_PUBLISH_AUTHORIZED=1)" >&2
  exit 2
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
remote="${FACTORTESTER_REMOTE:-launch-advisor}"
remote_git_root="${FACTORTESTER_REMOTE_GIT_ROOT:-/opt/factortester}"
remote_container_root="${FACTORTESTER_REMOTE_CONTAINER_ROOT:-/opt/factortester-container}"
remote_env="${FACTORTESTER_REMOTE_PUBLIC_ENV:-/etc/factortester-container/public.env}"
release_retention="${FACTORTESTER_PUBLIC_RELEASE_RETENTION:-3}"

[[ "$release_retention" =~ ^[1-9][0-9]*$ ]] || {
  echo "FACTORTESTER_PUBLIC_RELEASE_RETENTION must be a positive integer" >&2
  exit 2
}

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

remote_exec() {
  "${ssh_command[@]}" "$remote" "$@"
}

for command in git ssh; do
  command -v "$command" >/dev/null || {
    echo "missing local command: $command" >&2
    exit 2
  }
done

[[ "$(git -C "$repo_root" branch --show-current)" == "main" ]] || {
  echo "run this command from the main worktree" >&2
  exit 2
}
[[ -z "$(git -C "$repo_root" status --porcelain)" ]] || {
  echo "main worktree must be clean before publication" >&2
  exit 2
}

git -C "$repo_root" fetch origin
[[ "$(git -C "$repo_root" rev-parse feat)" == "$(git -C "$repo_root" rev-parse origin/feat)" ]] || {
  echo "feat must equal origin/feat before publication" >&2
  exit 2
}
for baseline in origin/main origin/feat; do
  git -C "$repo_root" merge-base --is-ancestor "$baseline" main || {
    echo "main must include $baseline before publication" >&2
    exit 2
  }
done
revision="$(git -C "$repo_root" rev-parse main)"

echo "Pushing main $revision to GitHub"
git -C "$repo_root" push origin main

remote_exec "command -v git >/dev/null && command -v docker >/dev/null && command -v flock >/dev/null"
remote_exec "test -d '$remote_git_root/repo.git' && sudo test -f '$remote_env'"

printf -v git_ssh_command '%q ' "${ssh_command[@]}"
git_ssh_command="${git_ssh_command% }"
echo "Pushing missing Git objects to $remote"
GIT_SSH_COMMAND="$git_ssh_command" git -C "$repo_root" push \
  "$remote:$remote_git_root/repo.git" "main:refs/heads/main"

remote_revision="$(
  remote_exec "git --git-dir='$remote_git_root/repo.git' rev-parse refs/heads/main"
)"
[[ "$remote_revision" == "$revision" ]] || {
  echo "remote revision mismatch: $remote_revision != $revision" >&2
  exit 1
}

remote_exec bash -s -- \
  "$revision" "$remote_git_root" "$remote_container_root" "$remote_env" \
  "$release_retention" <<'REMOTE'
set -Eeuo pipefail

revision="$1"
git_root="$2"
container_root="$3"
production_env="$4"
release_retention="$5"
activation_script="$(mktemp "${TMPDIR:-/tmp}/factortester-activate.XXXXXX")"
cleanup() {
  rm -f "$activation_script"
}
trap cleanup EXIT
git --git-dir="$git_root/repo.git" show \
  "$revision:scripts/server/activate_public_revision.sh" \
  > "$activation_script"
chmod 0700 "$activation_script"
bash "$activation_script" \
  "$revision" "$git_root" "$container_root" "$production_env" \
  "$release_retention"
REMOTE

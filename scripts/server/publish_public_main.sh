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

for command in git ssh tar; do
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

skip_github="${FACTORTESTER_SKIP_GITHUB_PUSH:-0}"
if [[ "$skip_github" != "1" ]]; then
  git -C "$repo_root" fetch origin
  [[ "$(git -C "$repo_root" rev-parse feat)" == "$(git -C "$repo_root" rev-parse origin/feat)" ]] || {
    echo "feat must equal origin/feat before publication" >&2
    exit 2
  }
fi
for baseline in origin/main origin/feat; do
  git -C "$repo_root" merge-base --is-ancestor "$baseline" main || {
    echo "main must include $baseline before publication" >&2
    exit 2
  }
done
nautilus_revision="$(bash "$repo_root/scripts/server/nautilus_vendor_revision.sh")"
export FACTORTESTER_NAUTILUS_VENDOR_REVISION="$nautilus_revision"

# Fail before sending artifacts or Git when the host lacks named contexts.
remote_exec "docker compose version >/dev/null && docker buildx version >/dev/null" || {
  echo "public deployment requires Docker Compose and Buildx; install the build plugin before retry" >&2; exit 2;
}

# Finished native artifacts are versioned separately from Git source releases.
source "$repo_root/scripts/server/nautilus_build_identity.sh"
native_build_id="$(nautilus_build_identity "$repo_root" "$repo_root/vendor/nautilus_trader" linux/amd64)"
native_artifact_root="$remote_container_root/native-wheels"
native_context="$native_artifact_root/$native_build_id"
if remote_exec "test -f '$native_context/checksums.sha256' && test \"\$(cat '$native_context/build-id.txt')\" = '$native_build_id' && cd '$native_context' && sha256sum -c checksums.sha256 >/dev/null 2>&1"; then
  echo "public native artifacts cache=hit build_id=$native_build_id"
else
  local_native_context="$(bash "$repo_root/scripts/server/prepare_nautilus_wheel_for_build.sh")"
  remote_exec "sudo install -d -m 0755 -o \"\$(id -u)\" -g \"\$(id -g)\" '$native_artifact_root'"
  artifact_budget_mb="${TR_NATIVE_ARTIFACT_MAX_MB:-512}"
  [[ "$artifact_budget_mb" =~ ^[1-9][0-9]*$ ]] || { echo "invalid native artifact budget" >&2; exit 2; }
  incoming_kb="$(du -sk "$local_native_context" | awk '{print $1}')"
  remote_exec "used=\$(du -sk '$native_artifact_root' | awk '{print \$1}'); test \$((used + $incoming_kb)) -le $((artifact_budget_mb * 1024))" || {
    echo "native artifacts exceed ${artifact_budget_mb}MiB budget; retain current/rollback and clean unused artifacts before retry" >&2; exit 3;
  }
  upload_context="$(remote_exec "mktemp -d '$native_artifact_root/.upload.XXXXXX'")"
  trap 'remote_exec "rm -rf -- \"$upload_context\"" >/dev/null 2>&1 || true' EXIT
  # Only the two wheels and their receipt are sent, never a source/data tree.
  tar -C "$local_native_context" -cf - . | "${ssh_command[@]}" "$remote" "tar -xf - -C '$upload_context'"
  remote_exec "cd '$upload_context' && sha256sum -c checksums.sha256 && test \"\$(cat build-id.txt)\" = '$native_build_id' && test ! -e '$native_context' && mv '$upload_context' '$native_context'"
  trap - EXIT
  echo "public native artifacts cache=stored build_id=$native_build_id"
fi

revision="$(git -C "$repo_root" rev-parse main)"

if [[ "$skip_github" == "1" ]]; then
  echo "Skipping GitHub push (FACTORTESTER_SKIP_GITHUB_PUSH=1)"
else
  echo "Pushing main $revision to GitHub"
  git -C "$repo_root" push origin main
fi

remote_exec "command -v git >/dev/null && command -v docker >/dev/null && command -v flock >/dev/null"
remote_exec "test -d '$remote_git_root/repo.git' && sudo test -f '$remote_env'"

printf -v git_ssh_command '%q ' "${ssh_command[@]}"
git_ssh_command="${git_ssh_command% }"
echo "Pushing missing Git objects to $remote"
GIT_SSH_COMMAND="$git_ssh_command" git -C "$repo_root" push --no-verify \
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
  "$release_retention" "$native_build_id" <<'REMOTE'
set -Eeuo pipefail

revision="$1"
git_root="$2"
container_root="$3"
production_env="$4"
release_retention="$5"
native_build_id="$6"
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
  "$release_retention" "$native_build_id"
REMOTE

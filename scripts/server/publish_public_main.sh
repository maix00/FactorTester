#!/usr/bin/env bash
set -Eeuo pipefail

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
release_root="$container_root/releases"
release_path="$release_root/$revision"
next_env="$production_env.next-$revision"
rollback_env="$production_env.before-$revision"
deployment_log="$container_root/deployments.log"

cleanup_old_application_releases() {
  local current_image_ref expected_suffix image_repository image_inventory
  local created_at repository tag release_candidate
  local keep_count=0
  declare -A keep_revisions=()

  while IFS=$'\t' read -r _ deployed_revision state; do
    [[ "$state" == "verified" ]] || continue
    [[ "$deployed_revision" =~ ^[0-9a-f]{40}$ ]] || continue
    [[ -z "${keep_revisions[$deployed_revision]:-}" ]] || continue
    keep_revisions["$deployed_revision"]=1
    ((keep_count += 1))
    ((keep_count >= release_retention)) && break
  done < <(
    awk '{ lines[NR] = $0 } END { for (i = NR; i >= 1; i--) print lines[i] }' \
      "$deployment_log"
  )
  keep_revisions["$revision"]=1

  if ! current_image_ref="$(
    sudo docker inspect --format '{{.Config.Image}}' \
      factortester-public-factortester-public-1
  )"; then
    echo "Warning: cannot identify the application image; skipping release cleanup" >&2
    return 0
  fi
  expected_suffix=":$revision"
  if [[ "$current_image_ref" != *"$expected_suffix" ]]; then
    echo "Warning: current image is not tagged with $revision; skipping release cleanup" >&2
    return 0
  fi
  image_repository="${current_image_ref%"$expected_suffix"}"
  if ! image_inventory="$(
    sudo docker image ls --format '{{.Repository}}\t{{.Tag}}\t{{.CreatedAt}}'
  )"; then
    echo "Warning: cannot list application images; skipping release cleanup" >&2
    return 0
  fi

  while IFS=$'\t' read -r repository tag created_at; do
    [[ "$repository" == "$image_repository" ]] || continue
    [[ "$tag" =~ ^[0-9a-f]{40}$ ]] || continue
    [[ -z "${keep_revisions[$tag]:-}" ]] || continue

    if ! sudo docker image rm "$repository:$tag"; then
      echo "Warning: could not remove old application image $repository:$tag" >&2
      continue
    fi
    release_candidate="$release_root/$tag"
    if [[ -e "$release_candidate/.git" ]]; then
      if ! git --git-dir="$git_root/repo.git" worktree remove "$release_candidate"; then
        echo "Warning: could not remove old release worktree $release_candidate" >&2
      fi
    fi
    echo "Removed old application release $tag (created $created_at)"
  done <<< "$image_inventory"
}

install -d "$release_root"
exec 9>"$container_root/.publish.lock"
flock -n 9 || {
  echo "another public release is in progress" >&2
  exit 1
}

if [[ ! -e "$release_path/.git" ]]; then
  git --git-dir="$git_root/repo.git" worktree add \
    --detach "$release_path" "$revision" >/dev/null
fi
[[ "$(git -C "$release_path" rev-parse HEAD)" == "$revision" ]]

sudo cp "$production_env" "$next_env"
sudo sed -i \
  "s/^FACTORTESTER_REVISION=.*/FACTORTESTER_REVISION=$revision/" \
  "$next_env"
sudo chmod 0600 "$next_env"

public_script="$release_path/scripts/server/factortester_public_container.sh"
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$next_env" \
  bash "$public_script" build factortester-public

old_revision="$(
  sudo sed -n 's/^FACTORTESTER_REVISION=//p' "$production_env" | head -n 1
)"
postgres_before="$(
  sudo docker inspect --format '{{.Id}}' \
    factortester-public-postgresql-control-1
)"
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" backup
sudo cp "$production_env" "$rollback_env"
sudo chmod 0600 "$rollback_env"

switched=0
rollback() {
  status=$?
  trap - ERR INT TERM
  if [[ "$switched" == "1" ]]; then
    echo "Public release failed; rolling back to $old_revision" >&2
    sudo cp "$rollback_env" "$production_env"
    old_script="$release_root/$old_revision/scripts/server/factortester_public_container.sh"
    sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
      bash "$old_script" restart-app || true
  fi
  exit "$status"
}
trap rollback ERR INT TERM

sudo mv "$next_env" "$production_env"
switched=1
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" restart-app
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" verify
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" restore-check

postgres_after="$(
  sudo docker inspect --format '{{.Id}}' \
    factortester-public-postgresql-control-1
)"
[[ "$postgres_before" == "$postgres_after" ]] || {
  echo "PostgreSQL container changed during application release" >&2
  exit 1
}

switched=0
trap - ERR INT TERM
printf '%s\t%s\t%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$revision" "verified" \
  >> "$deployment_log"
cleanup_old_application_releases
echo "Published public main $revision; PostgreSQL container preserved; retained $release_retention application releases"
REMOTE

#!/usr/bin/env bash
set -Eeuo pipefail

revision="${1:-}"
git_root="${2:-${FACTORTESTER_REMOTE_GIT_ROOT:-/opt/factortester}}"
container_root="${3:-${FACTORTESTER_REMOTE_CONTAINER_ROOT:-/opt/factortester-container}}"
production_env="${4:-${FACTORTESTER_REMOTE_PUBLIC_ENV:-/etc/factortester-container/public.env}}"
release_retention="${5:-${FACTORTESTER_PUBLIC_RELEASE_RETENTION:-3}}"
release_root="$container_root/releases"
release_path="$release_root/$revision"
next_env="$production_env.next-$revision"
rollback_env="$production_env.before-$revision"
deployment_log="$git_root/deployments.log"
publish_lock="$git_root/.publish.lock"

[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || {
  echo "revision must be a full Git SHA" >&2
  exit 2
}
[[ "$release_retention" =~ ^[1-9][0-9]*$ ]] || {
  echo "FACTORTESTER_PUBLIC_RELEASE_RETENTION must be a positive integer" >&2
  exit 2
}
for command in awk chmod date docker find flock git install sed sudo touch; do
  command -v "$command" >/dev/null || {
    echo "missing deployment command: $command" >&2
    exit 2
  }
done
[[ -d "$git_root/repo.git" ]] || {
  echo "missing public bare repository: $git_root/repo.git" >&2
  exit 2
}
sudo test -f "$production_env"
git --git-dir="$git_root/repo.git" cat-file -e "$revision^{commit}"

cleanup_old_application_releases() {
  local app_container_id current_image_ref expected_suffix image_repository
  local image_inventory
  local created_at repository tag release_candidate
  local keep_count=0
  declare -A keep_revisions=()
  declare -A blocked_worktrees=()

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

  if ! app_container_id="$(
    sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
      bash "$public_script" container-id factortester-public
  )" || [[ -z "$app_container_id" ]]; then
    echo "Warning: cannot identify the application container; skipping release cleanup" >&2
    return 0
  fi
  if ! current_image_ref="$(
    sudo docker inspect --format '{{.Config.Image}}' "$app_container_id"
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
      blocked_worktrees["$tag"]=1
      echo "Warning: could not remove old application image $repository:$tag" >&2
      continue
    fi
    echo "Removed old application image $tag (created $created_at)"
  done <<< "$image_inventory"

  while IFS= read -r release_candidate; do
    tag="${release_candidate##*/}"
    [[ "$tag" =~ ^[0-9a-f]{40}$ ]] || continue
    [[ -z "${keep_revisions[$tag]:-}" ]] || continue
    [[ -z "${blocked_worktrees[$tag]:-}" ]] || continue
    if ! git --git-dir="$git_root/repo.git" worktree remove "$release_candidate"; then
      echo "Warning: could not remove old release worktree $release_candidate" >&2
    else
      echo "Removed old application worktree $tag"
    fi
  done < <(find "$release_root" -mindepth 1 -maxdepth 1 -type d -print)
}

install -d "$release_root"
exec 9>"$publish_lock"
flock -n 9 || {
  echo "another public release is in progress" >&2
  exit 75
}
chmod 0600 "$publish_lock"
touch "$deployment_log"
chmod 0600 "$deployment_log"

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
old_revision="$(
  sudo sed -n 's/^FACTORTESTER_REVISION=//p' "$production_env" | head -n 1
)"
[[ "$old_revision" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Current production revision is invalid: $old_revision" >&2
  exit 1
}
if sudo grep -q '^FACTORTESTER_PUBLIC_CACHE_FROM=' "$next_env"; then
  sudo sed -i \
    "s|^FACTORTESTER_PUBLIC_CACHE_FROM=.*|FACTORTESTER_PUBLIC_CACHE_FROM=factortester-public:$old_revision|" \
    "$next_env"
else
  echo "FACTORTESTER_PUBLIC_CACHE_FROM=factortester-public:$old_revision" \
    | sudo tee -a "$next_env" >/dev/null
fi
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$next_env" \
  bash "$public_script" build factortester-public
postgres_before="$(
  sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
    bash "$public_script" container-id postgresql-control
)"
[[ -n "$postgres_before" ]]
postgres_before="$(sudo docker inspect --format '{{.Id}}' "$postgres_before")"
postgres_table_count_before="$(
  sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
    bash "$public_script" control-table-count | tr -d '\r\n'
)"
[[ "$postgres_table_count_before" =~ ^[0-9]+$ ]]
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" backup
sudo cp "$production_env" "$rollback_env"
sudo chmod 0600 "$rollback_env"

switched=0
app_stopped=0
rollback() {
  status=$?
  trap - ERR INT TERM
  if [[ "$switched" == "1" ]]; then
    echo "Public release failed; rolling back to $old_revision" >&2
    sudo cp "$rollback_env" "$production_env"
    old_script="$release_root/$old_revision/scripts/server/factortester_public_container.sh"
    sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
      bash "$old_script" restart-app || true
  elif [[ "$app_stopped" == "1" ]]; then
    old_script="$release_root/$old_revision/scripts/server/factortester_public_container.sh"
    sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
      bash "$old_script" restart-app || true
  fi
  exit "$status"
}
trap rollback ERR INT TERM

sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" stop-app
app_stopped=1

sudo mv "$next_env" "$production_env"
switched=1
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" restart-app
app_stopped=0
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" verify
sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
  bash "$public_script" restore-check "$postgres_table_count_before"

postgres_after="$(
  sudo env FACTORTESTER_PUBLIC_DOCKER_ENV_FILE="$production_env" \
    bash "$public_script" container-id postgresql-control
)"
[[ -n "$postgres_after" ]]
postgres_after="$(sudo docker inspect --format '{{.Id}}' "$postgres_after")"
[[ "$postgres_before" == "$postgres_after" ]] || {
  echo "PostgreSQL container changed during application release" >&2
  exit 1
}

switched=0
trap - ERR INT TERM
printf '%s\t%s\t%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$revision" "verified" \
  >> "$deployment_log"
if [[ "${FACTORTESTER_CLEANUP_RELEASES:-0}" == "1" ]]; then
  cleanup_old_application_releases
fi
echo "Published public main $revision; PostgreSQL container preserved; release cleanup is opt-in"

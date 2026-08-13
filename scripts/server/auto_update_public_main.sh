#!/usr/bin/env bash
set -Eeuo pipefail

git_root="${FACTORTESTER_REMOTE_GIT_ROOT:-/opt/factortester}"
container_root="${FACTORTESTER_REMOTE_CONTAINER_ROOT:-/opt/factortester-container}"
production_env="${FACTORTESTER_REMOTE_PUBLIC_ENV:-/etc/factortester-container/public.env}"
source_remote="${FACTORTESTER_PUBLIC_MAIN_REMOTE:-https://github.com/maix00/FactorTester.git}"
release_retention="${FACTORTESTER_PUBLIC_RELEASE_RETENTION:-3}"

for command in git mktemp sudo; do
  command -v "$command" >/dev/null || {
    echo "missing automatic update command: $command" >&2
    exit 2
  }
done
[[ -d "$git_root/repo.git" ]] || {
  echo "missing public bare repository: $git_root/repo.git" >&2
  exit 2
}
sudo test -f "$production_env"

git --git-dir="$git_root/repo.git" fetch \
  --no-tags "$source_remote" \
  "refs/heads/main:refs/heads/main"
candidate="$(
  git --git-dir="$git_root/repo.git" rev-parse refs/heads/main
)"
current="$(
  sudo sed -n 's/^FACTORTESTER_REVISION=//p' "$production_env" | head -n 1
)"

if [[ "$candidate" == "$current" ]]; then
  echo "Public main is already current at $candidate"
  exit 0
fi
if [[ "$current" =~ ^[0-9a-f]{40}$ ]] \
  && git --git-dir="$git_root/repo.git" cat-file -e "$current^{commit}" \
  && ! git --git-dir="$git_root/repo.git" merge-base --is-ancestor \
    "$current" "$candidate"; then
  echo "Refusing non-fast-forward public main update: $current -> $candidate" >&2
  exit 3
fi

activation_script="$(mktemp "${TMPDIR:-/tmp}/factortester-activate.XXXXXX")"
cleanup() {
  rm -f "$activation_script"
}
trap cleanup EXIT
git --git-dir="$git_root/repo.git" show \
  "$candidate:scripts/server/activate_public_revision.sh" \
  > "$activation_script"
chmod 0700 "$activation_script"

bash "$activation_script" \
  "$candidate" "$git_root" "$container_root" "$production_env" \
  "$release_retention"

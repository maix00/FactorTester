#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
vendor="$root/vendor/nautilus_trader"
[[ -d "$vendor/.git" || -f "$vendor/.git" ]] || {
  echo "vendor/nautilus_trader is not initialized" >&2
  exit 2
}
[[ -z "$(git -C "$vendor" status --porcelain)" ]] || {
  echo "vendor/nautilus_trader has uncommitted changes; commit/push them before deploy" >&2
  exit 2
}
revision="$(git -C "$vendor" rev-parse HEAD)"
gitlink="$(git -C "$root" rev-parse HEAD:vendor/nautilus_trader)"
[[ "$revision" == "$gitlink" ]] || {
  echo "Nautilus submodule HEAD $revision differs from gitlink $gitlink" >&2
  exit 2
}
printf '%s\n' "$revision"

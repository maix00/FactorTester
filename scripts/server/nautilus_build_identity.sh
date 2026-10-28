#!/usr/bin/env bash
# One cache identity for the composed runtime and its wheel staging step.
nautilus_build_identity() {
  local root="$1" src="$2" platform="$3" revision alpha_revision runtime_tree
  revision="$(git -C "$src" rev-parse HEAD)" || return
  alpha_revision="$(git -C "$root/vendor/py-alpha-lib" rev-parse HEAD)" || return
  runtime_tree="$(git -C "$root" ls-tree -r HEAD -- native/traderesearch_nautilus_runtime traderesearch_data/rust)" || return
  printf '%s\n' "$revision" "$alpha_revision" "$runtime_tree" "$platform" | shasum -a 256 | cut -d' ' -f1
}

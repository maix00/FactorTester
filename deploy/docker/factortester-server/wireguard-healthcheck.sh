#!/bin/sh
set -eu

readonly config_dir="${FACTORTESTER_WIREGUARD_SECRET_DIR:-/run/secrets/wireguard}"
found=0
for config in "$config_dir"/*.conf; do
    if [ ! -s "$config" ]; then
        continue
    fi
    found=1
    wg show "$(basename "$config" .conf)" >/dev/null
done
test "$found" -eq 1

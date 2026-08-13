#!/bin/sh
set -eu

readonly source_dir="${FACTORTESTER_WIREGUARD_SECRET_DIR:-/run/secrets/wireguard}"
readonly runtime_dir="/etc/wireguard"
active_configs=""

shutdown() {
    status="$?"
    trap - EXIT INT TERM
    for runtime_config in $active_configs; do
        wg-quick down "$runtime_config" >/dev/null 2>&1 || true
    done
    exit "$status"
}

trap shutdown EXIT INT TERM

if [ ! -d "$source_dir" ]; then
    echo "WireGuard configuration directory is missing: $source_dir" >&2
    exit 1
fi

mkdir -p "$runtime_dir"
chmod 0700 "$runtime_dir"
for source_config in "$source_dir"/*.conf; do
    if [ ! -s "$source_config" ]; then
        continue
    fi
    interface="$(basename "$source_config" .conf)"
    case "$interface" in
        *[!a-zA-Z0-9_=+.-]*|'')
            echo "Invalid WireGuard interface name: $interface" >&2
            exit 1
            ;;
    esac
    if [ "${#interface}" -gt 15 ]; then
        echo "WireGuard interface name exceeds 15 characters: $interface" >&2
        exit 1
    fi
    runtime_config="$runtime_dir/$interface.conf"
    cp "$source_config" "$runtime_config"
    chmod 0600 "$runtime_config"
    wg-quick up "$runtime_config"
    active_configs="$runtime_config $active_configs"
done

if [ -z "$active_configs" ]; then
    echo "No non-empty WireGuard *.conf files found in $source_dir" >&2
    exit 1
fi

# A configured interface is the liveness boundary. A current handshake and
# PostgreSQL availability are readiness details surfaced by FactorTester; they
# must not make the LAN Manager disappear or enter a restart loop.
while :; do
    sleep 3600 &
    wait "$!"
done

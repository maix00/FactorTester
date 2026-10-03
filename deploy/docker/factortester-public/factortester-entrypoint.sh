#!/bin/bash
set -Eeuo pipefail

interface="${FACTORTESTER_WIREGUARD_INTERFACE:-ftwg0}"
wireguard_source="${FACTORTESTER_WIREGUARD_CONFIG:-/run/secrets/federation-wireguard/ftwg0.conf}"
manager_pid=""
app_group="$(id -gn factortester)"
runtime_dir=/run/factortester-public
runtime_tls_cert="$runtime_dir/manager.crt"
runtime_tls_key="$runtime_dir/manager.key"

shutdown() {
    status=$?
    trap - EXIT INT TERM
    if [[ -n "$manager_pid" ]] && kill -0 "$manager_pid" 2>/dev/null; then
        kill -TERM "$manager_pid" 2>/dev/null || true
        wait "$manager_pid" 2>/dev/null || true
    fi
    wg-quick down "$interface" >/dev/null 2>&1 || true
    exit "$status"
}
trap shutdown EXIT INT TERM

[[ "${FACTORTESTER_HOT_RELOAD:-0}" == "0" ]] || {
    echo "Public FactorTester prohibits hot reload" >&2
    exit 2
}
[[ "${FACTORTESTER_SERVICE_DEBUG:-0}" == "0" ]] || {
    echo "Public FactorTester prohibits service debug mode" >&2
    exit 2
}
[[ -s "$wireguard_source" ]] || {
    echo "Missing federation WireGuard configuration: $wireguard_source" >&2
    exit 2
}
[[ -s /run/secrets/control-db.env ]] || {
    echo "Missing owner-only control database environment" >&2
    exit 2
}
[[ -s /run/secrets/manager-tls/manager.crt ]] || {
    echo "Missing Manager TLS certificate" >&2
    exit 2
}
[[ -s /run/secrets/manager-tls/manager.key ]] || {
    echo "Missing Manager TLS private key" >&2
    exit 2
}

install -m 0600 "$wireguard_source" "/etc/wireguard/$interface.conf"
wg-quick up "$interface"
[[ "$(sysctl -n net.ipv4.ip_forward)" == "1" ]] || {
    echo "FactorTester WireGuard gateway requires IPv4 forwarding" >&2
    exit 2
}
local_overlay_address="${FACTORTESTER_FEDERATION_LOCAL_ADDRESS:?set FACTORTESTER_FEDERATION_LOCAL_ADDRESS}"
ip -o address show dev "$interface" | grep -Fq " $local_overlay_address/" || {
    echo "WireGuard interface $interface does not own $local_overlay_address" >&2
    exit 2
}

control_line="$(grep -E '^FACTORTESTER_CONTROL_DATABASE_URL=' /run/secrets/control-db.env || true)"
[[ -n "$control_line" ]] || {
    echo "control-db.env has no FactorTester database URL" >&2
    exit 2
}
export FACTORTESTER_CONTROL_DATABASE_URL="${control_line#*=}"

install -d -o factortester -g "$app_group" -m 0700 "$runtime_dir"
install -o factortester -g "$app_group" -m 0600 \
    /run/secrets/manager-tls/manager.crt "$runtime_tls_cert"
install -o factortester -g "$app_group" -m 0600 \
    /run/secrets/manager-tls/manager.key "$runtime_tls_key"
export FACTORTESTER_MANAGER_TLS_CERT="$runtime_tls_cert"
export FACTORTESTER_MANAGER_TLS_KEY="$runtime_tls_key"
export FACTORTESTER_ARTIFACT_TLS_CERT="$runtime_tls_cert"
export FACTORTESTER_ARTIFACT_TLS_KEY="$runtime_tls_key"

for secret in manager-capability.key federation-registration.key federation-proxy.key; do
    source="/run/secrets/manager-state/$secret"
    if [[ -s "$source" && ! -e "/state/$secret" ]]; then
        install -o factortester -g "$app_group" -m 0600 "$source" "/state/$secret"
    fi
done
if [[ -s /state/federation-registration.key ]]; then
    export FACTORTESTER_FEDERATION_REGISTRATION_TOKEN
    FACTORTESTER_FEDERATION_REGISTRATION_TOKEN="$(
        tr -d '\r\n' < /state/federation-registration.key
    )"
fi

revision="$(tr -d '\r\n' < /opt/factortester/app/.deployment-revision)"
export GTHT_SOURCE_REVISION="$revision"
export FACTORTESTER_IMMUTABLE_SOURCE=1
export HOME=/state/home
export PYTHONPATH=/opt/factortester/app
install -d -o factortester -g "$app_group" /state/home /state/logs
chown -R factortester:"$app_group" /state
if [[ -s /run/secrets/manager-state/mihomo.yaml ]]; then
    install -o factortester -g "$app_group" -m 0600 \
        /run/secrets/manager-state/mihomo.yaml /state/mihomo.yaml
else
    rm -f /state/mihomo.yaml
fi
export FACTORTESTER_MIHOMO_BIN=/usr/local/bin/mihomo
export FACTORTESTER_MIHOMO_CONFIG_FILE=/state/mihomo.yaml
gosu factortester test -w /data || {
    echo "/data must be writable by FactorTester uid $(id -u factortester)" >&2
    exit 2
}

manager_args=(
    python -m server.manager.app
    --repo /opt/factortester/app
    --host 0.0.0.0
    --port 7998
    --python /usr/local/bin/python
    --data-root /data
    --server-role main
    --server-id "${FACTORTESTER_SERVER_ID:?set FACTORTESTER_SERVER_ID}"
    --fixed-port 8000
    --fixed-branch main
    --state-root /state
    --daemon-socket /state/main-8000.sock
    --no-browser
)

if python -m server.manager.app --help 2>&1 | grep -q -- '--overlay-bind-address'; then
    manager_args+=(
        --overlay-bind-address "$local_overlay_address"
        --peer-port 17998
        --peer-data-port 17997
        --public-endpoint "${FACTORTESTER_MANAGER_PUBLIC_ENDPOINT:?set FACTORTESTER_MANAGER_PUBLIC_ENDPOINT}"
        --public-data-endpoint "${FACTORTESTER_ARTIFACT_PUBLIC_ENDPOINT:?set FACTORTESTER_ARTIFACT_PUBLIC_ENDPOINT}"
    )
elif [[ "${FACTORTESTER_REQUIRE_PEER_LISTENERS:-1}" == "1" ]]; then
    echo "This FactorTester revision lacks the #184 peer listener contract" >&2
    exit 2
fi

gosu factortester "${manager_args[@]}" &
manager_pid=$!

gosu factortester /usr/local/bin/start-fixed-service \
    --manager https://127.0.0.1:7998 \
    --capability-file /state/manager-capability.key \
    --port 8000 \
    --timeout "${FACTORTESTER_STARTUP_TIMEOUT:-180}"

wait "$manager_pid"

#!/bin/bash
set -Eeuo pipefail

interface="${FACTORTESTER_DB_WIREGUARD_INTERFACE:-dbwg0}"
wireguard_source="${FACTORTESTER_DB_WIREGUARD_CONFIG:-/run/secrets/database-wireguard/dbwg0.conf}"
runtime_dir=/run/factortester-postgres
hba_file="$runtime_dir/pg_hba.conf"
runtime_password_file="$runtime_dir/control-db-password"
runtime_migration_dump="$runtime_dir/factortester_control.dump"

shutdown_wireguard() {
    wg-quick down "$interface" >/dev/null 2>&1 || true
}
trap shutdown_wireguard EXIT

[[ -s "$wireguard_source" ]] || {
    echo "Missing database WireGuard configuration: $wireguard_source" >&2
    exit 2
}
[[ -s /run/secrets/postgres-tls/server.crt ]] || {
    echo "Missing PostgreSQL TLS certificate" >&2
    exit 2
}
[[ -s /run/secrets/postgres-tls/server.key ]] || {
    echo "Missing PostgreSQL TLS private key" >&2
    exit 2
}
[[ -s /run/secrets/control-db-password ]] || {
    echo "Missing FactorTester control database password" >&2
    exit 2
}

install -m 0600 "$wireguard_source" "/etc/wireguard/$interface.conf"
wg-quick up "$interface"
[[ "$(sysctl -n net.ipv4.ip_forward)" == "1" ]] || {
    echo "PostgreSQL WireGuard gateway requires IPv4 forwarding" >&2
    exit 2
}
database_local_address="${FACTORTESTER_DATABASE_LOCAL_ADDRESS:?set FACTORTESTER_DATABASE_LOCAL_ADDRESS}"
ip -o address show dev "$interface" | grep -Fq " $database_local_address/" || {
    echo "WireGuard interface $interface does not own $database_local_address" >&2
    exit 2
}

install -d -o postgres -g postgres -m 0700 "$runtime_dir"
install -o postgres -g postgres -m 0600 \
    /run/secrets/control-db-password "$runtime_password_file"
export FACTORTESTER_CONTROL_DB_PASSWORD_FILE="$runtime_password_file"
if [[ -s /run/migration/factortester_control.dump ]]; then
    install -o postgres -g postgres -m 0600 \
        /run/migration/factortester_control.dump "$runtime_migration_dump"
    export FACTORTESTER_POSTGRES_MIGRATION_DUMP="$runtime_migration_dump"
fi
install -o postgres -g postgres -m 0644 \
    /run/secrets/postgres-tls/server.crt "$runtime_dir/server.crt"
install -o postgres -g postgres -m 0600 \
    /run/secrets/postgres-tls/server.key "$runtime_dir/server.key"

{
    echo 'local all all trust'
    echo 'hostssl factortester_control factortester_control 172.30.185.2/32 scram-sha-256'
    IFS=',' read -ra cidrs <<< "${FACTORTESTER_DB_ALLOWED_WIREGUARD_CIDRS:-}"
    for raw in "${cidrs[@]}"; do
        cidr="${raw//[[:space:]]/}"
        [[ -z "$cidr" ]] && continue
        [[ "$cidr" =~ ^[0-9A-Fa-f:./]+$ ]] || {
            echo "Invalid database WireGuard CIDR: $cidr" >&2
            exit 2
        }
        printf 'hostssl factortester_control factortester_control %s scram-sha-256\n' "$cidr"
    done
    echo 'host all all 0.0.0.0/0 reject'
    echo 'host all all ::/0 reject'
} > "$hba_file"
chown postgres:postgres "$hba_file"
chmod 0600 "$hba_file"

/usr/local/bin/docker-entrypoint.sh "$@" \
    -c "listen_addresses=127.0.0.1,172.30.185.3,$database_local_address" \
    -c ssl=on \
    -c "ssl_cert_file=$runtime_dir/server.crt" \
    -c "ssl_key_file=$runtime_dir/server.key" \
    -c "hba_file=$hba_file" \
    -c password_encryption=scram-sha-256 &
postgres_pid=$!
trap 'kill -TERM "$postgres_pid" 2>/dev/null || true' INT TERM
wait "$postgres_pid"

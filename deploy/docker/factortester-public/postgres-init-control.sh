#!/bin/bash
set -Eeuo pipefail

password_file="${FACTORTESTER_CONTROL_DB_PASSWORD_FILE:-/run/secrets/control-db-password}"
[[ -s "$password_file" ]] || {
    echo "Missing FactorTester control database password" >&2
    exit 2
}
app_password="$(tr -d '\r\n' < "$password_file")"
[[ -n "$app_password" ]] || exit 2

psql --username "$POSTGRES_USER" --dbname postgres \
    --set=ON_ERROR_STOP=1 --set=app_password="$app_password" <<'SQL'
SELECT 'CREATE ROLE factortester_control LOGIN'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'factortester_control'
) \gexec
ALTER ROLE factortester_control PASSWORD :'app_password';
SELECT 'CREATE DATABASE factortester_control OWNER factortester_control ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'factortester_control'
) \gexec
SQL

dump="${FACTORTESTER_POSTGRES_MIGRATION_DUMP:-/run/migration/factortester_control.dump}"
if [[ -s "$dump" ]]; then
    pg_restore --exit-on-error --no-owner --role=factortester_control \
        --dbname=factortester_control "$dump"
fi

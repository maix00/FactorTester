#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"
compose_file="$repo_root/deploy/docker/factortester-public/compose.yaml"
env_file="${FACTORTESTER_PUBLIC_DOCKER_ENV_FILE:-/etc/factortester-container/public.env}"

usage() {
  cat <<'EOF'
Usage: scripts/server/factortester_public_container.sh COMMAND [ARGS...]

Commands:
  check-source   require a clean checkout and exact FACTORTESTER_REVISION
  config         render and validate Compose configuration
  build          build both versioned images explicitly
  up             start/reconcile from existing images; never builds or pulls
  restart-app    restart only FactorTester; PostgreSQL remains running
  status         show exactly the two business containers and health
  logs           follow logs (extra docker compose arguments accepted)
  down           stop containers but retain PostgreSQL volume and host data
  backup         write a checksummed PostgreSQL custom dump
  restore-check  restore the newest backup into an ephemeral database, compare,
                 and remove only that temporary database
  verify         verify ports, identities, revision, PostgreSQL, and no reload

Set FACTORTESTER_PUBLIC_DOCKER_ENV_FILE for a non-default owner-only env file.
EOF
}

[[ -f "$env_file" ]] || {
  echo "Missing public deployment environment: $env_file" >&2
  exit 1
}
set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

compose=(docker compose --env-file "$env_file" --file "$compose_file")
revision="${FACTORTESTER_REVISION:-}"

check_source() {
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || {
    echo "FACTORTESTER_REVISION must be a full Git SHA" >&2
    exit 2
  }
  [[ "$(git -C "$repo_root" rev-parse HEAD)" == "$revision" ]] || {
    echo "Checkout HEAD does not match FACTORTESTER_REVISION" >&2
    exit 2
  }
  git -C "$repo_root" diff --quiet
  git -C "$repo_root" diff --cached --quiet
}

backup_database() {
  backup_root="${FACTORTESTER_POSTGRES_BACKUP_DIR:?set FACTORTESTER_POSTGRES_BACKUP_DIR}"
  install -d -m 0700 "$backup_root"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="$backup_root/factortester_control-$stamp.dump"
  "${compose[@]}" exec -T postgresql-control \
    pg_dump --format=custom --username=postgres --dbname=factortester_control > "$target"
  chmod 0600 "$target"
  sha256sum "$target" > "$target.sha256"
  chmod 0600 "$target.sha256"
  echo "$target"
}

restore_check() {
  backup_root="${FACTORTESTER_POSTGRES_BACKUP_DIR:?set FACTORTESTER_POSTGRES_BACKUP_DIR}"
  dump="$(find "$backup_root" -maxdepth 1 -type f -name 'factortester_control-*.dump' -print | sort | tail -n 1)"
  [[ -n "$dump" ]] || { echo "No PostgreSQL backup found" >&2; exit 1; }
  (cd "$(dirname "$dump")" && sha256sum --check "$(basename "$dump").sha256")
  restore_db="factortester_restore_check_$$"
  cleanup_restore() {
    "${compose[@]}" exec -T postgresql-control \
      dropdb --if-exists --force --username=postgres "$restore_db" >/dev/null 2>&1 || true
  }
  trap cleanup_restore EXIT
  "${compose[@]}" exec -T postgresql-control \
    createdb --username=postgres --template=template0 --encoding=UTF8 "$restore_db"
  "${compose[@]}" exec -T postgresql-control \
    pg_restore --exit-on-error --no-owner --username=postgres --dbname="$restore_db" < "$dump"
  original_count="$("${compose[@]}" exec -T postgresql-control \
    psql -At --username=postgres --dbname=factortester_control \
      -c "select count(*) from pg_catalog.pg_tables where schemaname='public'")"
  restored_count="$("${compose[@]}" exec -T postgresql-control \
    psql -At --username=postgres --dbname="$restore_db" \
      -c "select count(*) from pg_catalog.pg_tables where schemaname='public'")"
  [[ "$original_count" == "$restored_count" ]] || {
    echo "Restore table-count mismatch: $original_count != $restored_count" >&2
    exit 1
  }
  echo "Restore check passed ($restored_count public tables)"
}

verify() {
  mapfile -t services < <("${compose[@]}" config --services | sort)
  [[ "${services[*]}" == "factortester-public postgresql-control" ]] || {
    echo "Deployment must contain exactly two services" >&2
    exit 1
  }
  [[ -z "$("${compose[@]}" port factortester-public 8000 2>/dev/null || true)" ]]
  [[ -z "$("${compose[@]}" port postgresql-control 5432 2>/dev/null || true)" ]]
  app_revision="$("${compose[@]}" exec -T factortester-public \
    cat /opt/factortester/app/.deployment-revision | tr -d '\r\n')"
  [[ "$app_revision" == "$revision" ]]
  [[ "$("${compose[@]}" exec -T factortester-public printenv FACTORTESTER_HOT_RELOAD)" == "0" ]]
  app_key="$("${compose[@]}" exec -T factortester-public wg show ftwg0 public-key)"
  db_key="$("${compose[@]}" exec -T postgresql-control wg show dbwg0 public-key)"
  [[ -n "$app_key" && -n "$db_key" && "$app_key" != "$db_key" ]]
  "${compose[@]}" exec -T factortester-public sh -c '
control_line="$(grep -E '\''^FACTORTESTER_CONTROL_DATABASE_URL='\'' \
  /run/secrets/control-db.env || true)"
if [ -z "$control_line" ]; then
  echo "control-db.env has no FactorTester database URL" >&2
  exit 1
fi
export FACTORTESTER_CONTROL_DATABASE_URL="${control_line#*=}"
exec python -
' <<'PY'
import os
import psycopg
with psycopg.connect(os.environ["FACTORTESTER_CONTROL_DATABASE_URL"]) as db:
    assert db.execute("select current_database()").fetchone()[0] == "factortester_control"
PY
  curl --fail --silent --show-error --insecure \
    "https://127.0.0.1:${FACTORTESTER_MANAGER_HOST_PORT:-7998}/" >/dev/null
  curl --fail --silent --show-error --insecure \
    "https://127.0.0.1:${FACTORTESTER_ARTIFACT_HOST_PORT:-7997}/healthz" >/dev/null
  echo "Public container verification passed"
}

command="${1:-}"
[[ -n "$command" ]] || { usage; exit 2; }
shift
case "$command" in
  check-source) check_source ;;
  config) "${compose[@]}" config "$@" ;;
  build) check_source; "${compose[@]}" build "$@" ;;
  up) "${compose[@]}" up --detach --no-build --remove-orphans --wait "$@" ;;
  restart-app) "${compose[@]}" up --detach --no-build --no-deps --force-recreate --wait factortester-public "$@" ;;
  status) "${compose[@]}" ps "$@" ;;
  logs) "${compose[@]}" logs --follow "$@" ;;
  down) "${compose[@]}" down --remove-orphans "$@" ;;
  backup) backup_database ;;
  restore-check) restore_check ;;
  verify) verify ;;
  -h|--help|help) usage ;;
  *) echo "Unknown command: $command" >&2; usage >&2; exit 2 ;;
esac

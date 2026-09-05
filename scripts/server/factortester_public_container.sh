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
  container-id   print one service's current container ID
  build          build both versioned images explicitly
  up             start/reconcile from existing images; never builds or pulls
  restart-app    restart only FactorTester; PostgreSQL remains running
  stop-app       stop only FactorTester; PostgreSQL remains running
  status         show exactly the two business containers and health
  logs           follow logs (extra docker compose arguments accepted)
  down           stop containers but retain PostgreSQL volume and host data
  backup         write a checksummed PostgreSQL custom dump
  restore-check  restore the newest backup into an ephemeral database, compare,
                 and remove only that temporary database
  migrate-factor-identities
                 back up SQLite, migrate source metadata and editable factor
                 identities, discard irrecoverable v1 drafts, then verify
  restore-factor-identities
                 restore the pre-migration SQLite backup after failed release
  migrate-factor-control-identities
                 apply the prepared account-domain plan to PostgreSQL
  restore-factor-control-identities
                 restore PostgreSQL account-domain rows after failed release
  finalize-factor-identities
                 clear the rollback marker after successful verification
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

control_table_count() {
  "${compose[@]}" exec -T postgresql-control \
    psql -At --username=postgres --dbname=factortester_control \
      -c "select count(*) from pg_catalog.pg_tables where schemaname='public'"
}

restore_check() {
  expected_table_count="${1:-}"
  if [[ -n "$expected_table_count" && ! "$expected_table_count" =~ ^[0-9]+$ ]]; then
    echo "expected table count must be a non-negative integer" >&2
    exit 2
  fi
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
  original_count="${expected_table_count:-$(control_table_count)}"
  restored_count="$("${compose[@]}" exec -T postgresql-control \
    psql -At --username=postgres --dbname="$restore_db" \
      -c "select count(*) from pg_catalog.pg_tables where schemaname='public'")"
  [[ "$original_count" == "$restored_count" ]] || {
    echo "Restore table-count mismatch: $original_count != $restored_count" >&2
    exit 1
  }
  echo "Restore check passed ($restored_count public tables)"
}

migrate_factor_identities() {
  image="${FACTORTESTER_PUBLIC_IMAGE:-factortester-public}:$revision"
  docker run --rm --entrypoint /bin/sh \
    --volume "${FACTORTESTER_DATA_ROOT:?set FACTORTESTER_DATA_ROOT}:/data" \
    --volume "${FACTORTESTER_STATE_ROOT:?set FACTORTESTER_STATE_ROOT}:/state" \
    --volume "${FACTORTESTER_SETTINGS_FILE:?set FACTORTESTER_SETTINGS_FILE}:/opt/factortester/.settings:ro" \
    "$image" -c '
set -eu
export HOME=/state/home
export PYTHONPATH=/opt/factortester/app/tools/cli/agent-harness:/opt/factortester/app
cd /opt/factortester/app
gosu factortester python - <<"PY"
import sqlite3
import time
from pathlib import Path
import settings

source = Path(settings.CACHE_DB_PATH)
backup = source.with_name(source.name + f".pre-factor-v2-{int(time.time())}.bak")
with sqlite3.connect(source) as current, sqlite3.connect(backup) as snapshot:
    current.backup(snapshot)
    if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite migration backup failed integrity check")
Path("/state/factor-v2-migration-backup-path").write_text(str(backup), encoding="utf-8")
PY
gosu factortester python -m tools.migrations.migrate_factor_source_metadata
gosu factortester python -m tools.migrations.migrate_factor_formula_identity \
  --apply \
  --control-plan /state/factor-v2-control-plan.json
gosu factortester python -m tools.migrations.migrate_factor_catalog_projection --apply
gosu factortester python - <<"PY"
import json
import sqlite3
import settings

with sqlite3.connect(settings.CACHE_DB_PATH) as connection:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite failed integrity check after factor migration")
    legacy = connection.execute(
        "SELECT count(*) FROM research_configurations WHERE schema_version=1"
    ).fetchone()[0]
    if legacy:
        raise RuntimeError(f"SQLite still contains {legacy} schema-1 configurations")
    legacy_manifests = sum(
        "factor_revision_manifests" in (
            json.loads(raw).get("shared") or {}
        )
        for (raw,) in connection.execute(
            "SELECT payload_json FROM research_configurations "
            "WHERE schema_version=2"
        ).fetchall()
    )
    if legacy_manifests:
        raise RuntimeError(
            "SQLite still contains "
            f"{legacy_manifests} legacy factor revision manifests"
        )
PY
'
}

migrate_factor_control_identities() {
  marker="${FACTORTESTER_STATE_ROOT:?set FACTORTESTER_STATE_ROOT}/factor-v2-control-applied"
  plan="${FACTORTESTER_STATE_ROOT}/factor-v2-control-plan.json"
  [[ -f "$plan" ]] || { echo "factor control-domain plan is unavailable" >&2; exit 1; }
  "${compose[@]}" run --rm --no-deps --entrypoint /bin/sh factortester-public -lc '
set -eu
export PYTHONPATH=/opt/factortester/app/tools/cli/agent-harness:/opt/factortester/app
cd /opt/factortester/app
python -m tools.migrations.migrate_factor_control_domain \
  --plan /state/factor-v2-control-plan.json
'
  touch "$marker"
  chmod 0600 "$marker"
}

restore_factor_control_identities() {
  marker="${FACTORTESTER_STATE_ROOT:?set FACTORTESTER_STATE_ROOT}/factor-v2-control-applied"
  [[ -f "$marker" ]] || return 0
  "${compose[@]}" run --rm --no-deps --entrypoint /bin/sh factortester-public -lc '
set -eu
export PYTHONPATH=/opt/factortester/app/tools/cli/agent-harness:/opt/factortester/app
cd /opt/factortester/app
python -m tools.migrations.migrate_factor_control_domain \
  --plan /state/factor-v2-control-plan.json --restore
'
  rm -f "$marker"
}

restore_factor_identities() {
  image="${FACTORTESTER_PUBLIC_IMAGE:-factortester-public}:$revision"
  docker run --rm --entrypoint /bin/sh \
    --volume "${FACTORTESTER_DATA_ROOT:?set FACTORTESTER_DATA_ROOT}:/data" \
    --volume "${FACTORTESTER_STATE_ROOT:?set FACTORTESTER_STATE_ROOT}:/state" \
    --volume "${FACTORTESTER_SETTINGS_FILE:?set FACTORTESTER_SETTINGS_FILE}:/opt/factortester/.settings:ro" \
    "$image" -c '
set -eu
export HOME=/state/home
export PYTHONPATH=/opt/factortester/app/tools/cli/agent-harness:/opt/factortester/app
cd /opt/factortester/app
gosu factortester python - <<"PY"
import sqlite3
from pathlib import Path
import settings

marker = Path("/state/factor-v2-migration-backup-path")
backup = Path(marker.read_text(encoding="utf-8").strip())
if not backup.is_file():
    raise RuntimeError("pre-migration SQLite backup is unavailable")
with sqlite3.connect(backup) as snapshot, sqlite3.connect(settings.CACHE_DB_PATH) as current:
    if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("pre-migration SQLite backup is corrupt")
    snapshot.backup(current)
marker.unlink()
PY
'
}

finalize_factor_identities() {
  state_root="${FACTORTESTER_STATE_ROOT:?set FACTORTESTER_STATE_ROOT}"
  rm -f "$state_root/factor-v2-migration-backup-path" \
    "$state_root/factor-v2-control-applied" \
    "$state_root/factor-v2-control-plan.json"
}

assert_unpublished_tcp_port() {
  local service="$1"
  local port="$2"
  local container_id binding
  container_id="$("${compose[@]}" ps --quiet "$service")"
  [[ -n "$container_id" ]] || {
    echo "$service is not running" >&2
    return 1
  }
  binding="$(docker inspect --format \
    "{{json (index .HostConfig.PortBindings \"$port/tcp\")}}" \
    "$container_id")"
  [[ "$binding" == "null" ]] || {
    echo "$service publishes internal TCP port $port: $binding" >&2
    return 1
  }
}

verify() {
  mapfile -t services < <("${compose[@]}" config --services | sort)
  [[ "${services[*]}" == "factortester-public postgresql-control" ]] || {
    echo "Deployment must contain exactly two services" >&2
    exit 1
  }
  assert_unpublished_tcp_port factortester-public 8000
  assert_unpublished_tcp_port postgresql-control 5432
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
export PYTHONPATH=/opt/factortester/app/tools/cli/agent-harness:/opt/factortester/app
exec python -
' <<'PY'
import os
import psycopg

from server.manager.storage.control_db import (
    CONTROL_DATABASE_SCHEMA_VERSION,
    control_store_from_env,
)

control_store = control_store_from_env()
if control_store is None:
    raise RuntimeError("FactorTester control database is not configured")
control_store.ensure_schema()

with psycopg.connect(os.environ["FACTORTESTER_CONTROL_DATABASE_URL"]) as db:
    database_name = db.execute("select current_database()").fetchone()[0]
    if database_name != "factortester_control":
        raise RuntimeError(f"unexpected control database: {database_name}")
    schema_version = db.execute(
        "select coalesce(max(version), 0) from control_schema_migrations"
    ).fetchone()[0]
    if schema_version != CONTROL_DATABASE_SCHEMA_VERSION:
        raise RuntimeError(
            "control database schema mismatch: "
            f"{schema_version} != {CONTROL_DATABASE_SCHEMA_VERSION}"
        )
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
  container-id) "${compose[@]}" ps --quiet "$@" ;;
  control-table-count) control_table_count ;;
  build) check_source; "${compose[@]}" build "$@" ;;
  up) "${compose[@]}" up --detach --no-build --remove-orphans --wait "$@" ;;
  restart-app) "${compose[@]}" up --detach --no-build --no-deps --force-recreate --wait factortester-public "$@" ;;
  stop-app) "${compose[@]}" stop factortester-public "$@" ;;
  status) "${compose[@]}" ps "$@" ;;
  logs) "${compose[@]}" logs --follow "$@" ;;
  down) "${compose[@]}" down --remove-orphans "$@" ;;
  backup) backup_database ;;
  restore-check) restore_check "$@" ;;
  migrate-factor-identities) migrate_factor_identities ;;
  migrate-factor-control-identities) migrate_factor_control_identities ;;
  restore-factor-control-identities) restore_factor_control_identities ;;
  restore-factor-identities) restore_factor_identities ;;
  finalize-factor-identities) finalize_factor_identities ;;
  verify) verify ;;
  -h|--help|help) usage ;;
  *) echo "Unknown command: $command" >&2; usage >&2; exit 2 ;;
esac

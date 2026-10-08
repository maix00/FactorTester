#!/usr/bin/env python3
"""Migrate the central control slice of one SQLite database to PostgreSQL.

This is intentionally not a wholesale SQLite replication tool.  Accounts,
organizations, levels, quotas, and profile metadata become central control
data.  Job execution facts, local queue state, artifact indexes, and caches
remain on the server that owns them.  Factor source bodies are counted and
reported, but are not copied into PostgreSQL; they need a Git/CAS snapshot
with an immutable version before a 7997 data-plane migration.

The source database is opened read-only.  When ``--apply`` is used, a SQLite
Online Backup is created first unless ``--no-backup`` is explicitly selected.
The command is idempotent for the imported control rows and prints a JSON
report suitable for an operator log.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable, Mapping
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.manager.storage.control_db import (  # noqa: E402
    CONTROL_DATABASE_ENV,
    ControlDatabaseConfig,
    PostgresControlStore,
)


CONTROL_TABLES: tuple[str, ...] = (
    "accounts",
    "organizations",
    "levels",
    "user_storage_policies",
    "factor_family_sources",
)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"SQLite source database does not exist: {resolved}")
    connection = sqlite3.connect(
        f"file:{quote(str(resolved), safe='/')}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _read_table(
    connection: sqlite3.Connection,
    table: str,
    columns: Iterable[str],
) -> list[dict[str, Any]]:
    if not _table_exists(connection, table):
        return []
    requested = ", ".join(columns)
    return [dict(row) for row in connection.execute(
        f"SELECT {requested} FROM {table}"
    ).fetchall()]


def load_sqlite_control_snapshot(source_db: str | os.PathLike[str]) -> dict[str, Any]:
    """Read only the control-plane tables without creating missing schemas."""
    path = Path(source_db).expanduser().resolve()
    with _connect_readonly(path) as connection:
        accounts = _read_table(
            connection,
            "accounts",
            (
                "username", "alias", "salt", "hash", "role", "is_admin",
                "is_developer", "organization_id", "organization_name",
                "level_id", "parent_username", "updated_at",
            ),
        )
        organizations = _read_table(
            connection,
            "organizations",
            ("id", "name", "description", "updated_at"),
        )
        levels = _read_table(
            connection,
            "levels",
            (
                "id", "organization_id", "name", "parent_level_id",
                "manager_username", "updated_at",
            ),
        )
        quotas = _read_table(
            connection,
            "user_storage_policies",
            ("owner", "quota_bytes", "updated_at"),
        )
        source_rows = _read_table(
            connection,
            "factor_family_sources",
            (
                "source_kind", "owner_username", "factor_id", "factor_name",
                "updated_at",
            ),
        )
    return {
        "source_db": str(path),
        "accounts": accounts,
        "organizations": organizations,
        "levels": levels,
        "quotas": quotas,
        "source_rows": source_rows,
    }


def _drop_local_paths(value: Any, *, depth: int = 0) -> Any:
    """Keep bounded profile metadata while removing device-local paths/secrets."""
    if depth > 6:
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        blocked = {
            "password", "password_hash", "secret", "token", "access_token",
            "workspace_root", "worktree_path", "git_common_dir",
            "research_root", "strategy_root", "path", "absolute_path",
            "local_path", "source_code", "session_ref",
        }
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in blocked or normalized_key.endswith("_path"):
                continue
            cleaned = _drop_local_paths(item, depth=depth + 1)
            if cleaned is not None:
                result[str(key)] = cleaned
        return result
    if isinstance(value, (list, tuple)):
        return [
            cleaned
            for item in list(value)[:256]
            if (cleaned := _drop_local_paths(item, depth=depth + 1)) is not None
        ]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def profile_metadata(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the server-safe portion of a local Profile JSON document."""
    profile_id = str(value.get("profile_id") or "").strip()
    binding = value.get("session_binding")
    principal = str(binding.get("principal_ref") or "").strip() if isinstance(binding, Mapping) else ""
    if not profile_id or not principal:
        return None
    allowed = {
        "schema_version", "profile_id", "status", "display_name",
        "initialization_sources", "session_binding",
        "factor_workspace_binding", "strategy_workspace_binding", "agents",
    }
    payload = _drop_local_paths({key: value.get(key) for key in allowed if key in value})
    if not isinstance(payload, dict):
        payload = {}
    payload["profile_id"] = profile_id
    payload["display_name"] = str(value.get("display_name") or profile_id)
    payload["session_binding"] = {"principal_ref": principal}
    return {
        "principal": principal,
        "profile_id": profile_id,
        "display_name": payload["display_name"],
        "payload": payload,
    }


def load_profile_metadata(client_root: str | os.PathLike[str] | None) -> list[dict[str, Any]]:
    if not client_root:
        return []
    root = Path(client_root).expanduser().resolve() / "profiles"
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"))[:512]:
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, Mapping):
            profile = profile_metadata(value)
            if profile is not None:
                result.append(profile)
    return result


def backup_sqlite(source_db: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    """Create a consistent SQLite Online Backup without copying a live file."""
    source = Path(source_db).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if source == target:
        raise ValueError("SQLite backup destination must differ from source")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite SQLite backup: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with _connect_readonly(source) as source_connection:
        target_connection = sqlite3.connect(target)
        try:
            source_connection.backup(target_connection)
            target_connection.commit()
        finally:
            target_connection.close()
    return target


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_backup_path(source_db: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return source_db.with_name(f"{source_db.name}.pre-control-migration-{stamp}.sqlite")


def snapshot_report(snapshot: Mapping[str, Any], profiles: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "source_db": snapshot.get("source_db", ""),
        "accounts": len(snapshot.get("accounts") or []),
        "organizations": len(snapshot.get("organizations") or []),
        "levels": len(snapshot.get("levels") or []),
        "quotas": len(snapshot.get("quotas") or []),
        "profiles": len(profiles),
        "factor_source_metadata": len(snapshot.get("source_rows") or []),
        "factor_source_bodies_migrated": 0,
    }


def migrate(
    *,
    source_db: str | os.PathLike[str],
    client_root: str | os.PathLike[str] | None,
    database_url: str,
    apply: bool,
    backup_path: str | os.PathLike[str] | None,
    no_backup: bool,
) -> dict[str, Any]:
    source = Path(source_db).expanduser().resolve()
    snapshot = load_sqlite_control_snapshot(source)
    profiles = load_profile_metadata(client_root)
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "snapshot": snapshot_report(snapshot, profiles),
        "backup": None,
        "verification": {},
        "notes": [
            "research_jobs, artifacts, queue state, and other host-local SQLite facts were not copied",
            "factor source bodies were not copied to PostgreSQL; migrate them through Git/CAS and 7997",
        ],
    }
    if not apply:
        return report
    if not database_url:
        raise ValueError(
            f"{CONTROL_DATABASE_ENV} or --database-url is required with --apply"
        )
    if not no_backup:
        target = Path(backup_path).expanduser().resolve() if backup_path else _default_backup_path(source)
        created = backup_sqlite(source, target)
        report["backup"] = {"path": str(created), "sha256": sha256_file(created)}

    config = ControlDatabaseConfig.from_url(database_url)
    store = PostgresControlStore(config)
    store.ensure_schema()
    store.replace_organizations(snapshot["organizations"])
    store.replace_levels(snapshot["levels"])
    store.replace_accounts(snapshot["accounts"])
    for row in snapshot["quotas"]:
        owner = str(row.get("owner") or "").strip()
        if owner:
            store.set_quota(owner, int(row.get("quota_bytes") or 0))
    for profile in profiles:
        store.upsert_profile(
            str(profile["principal"]),
            str(profile["profile_id"]),
            str(profile["display_name"]),
            profile.get("payload") if isinstance(profile.get("payload"), Mapping) else {},
        )
    report["verification"] = {
        "accounts": len(store.load_accounts()),
        "organizations": len(store.load_organizations()),
        "levels": len(store.load_levels()),
        "profiles": sum(
            len(store.list_profiles(principal))
            for principal in {
                str(profile["principal"]) for profile in profiles
            }
        ),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, help="SQLite unified database to read")
    parser.add_argument("--client-root", default="", help="optional local Client root containing profiles/*.json")
    parser.add_argument(
        "--database-url",
        default=os.environ.get(CONTROL_DATABASE_ENV, ""),
        help=f"PostgreSQL URL; defaults to {CONTROL_DATABASE_ENV}",
    )
    parser.add_argument("--apply", action="store_true", help="write the control slice to PostgreSQL")
    parser.add_argument("--backup-path", default="", help="SQLite Online Backup destination")
    parser.add_argument("--no-backup", action="store_true", help="skip the pre-migration SQLite backup")
    args = parser.parse_args(argv)
    try:
        result = migrate(
            source_db=args.source_db,
            client_root=args.client_root or None,
            database_url=args.database_url,
            apply=bool(args.apply),
            backup_path=args.backup_path or None,
            no_backup=bool(args.no_backup),
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"SQLite control migration failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

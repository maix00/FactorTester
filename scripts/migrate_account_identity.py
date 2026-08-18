#!/usr/bin/env python3
"""Plan or apply the one-time FactorTester account identity reset.

The default action is a dry run.  Applying requires a previously written
manifest, ``--delete-other-users``, a SQLite backup, and a PostgreSQL dump.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import re
import sqlite3
import subprocess
import sys
import time
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Allow the documented ``python scripts/...`` invocation to resolve the
# repository's settings and server packages without requiring PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import settings
from server.manager.domain.organization_scope import canonical_username
from server.manager.storage.identity_migration import (
    apply_postgres_identity_migration,
    apply_sqlite_identity_migration,
    apply_user_root_identity_migration,
    backup_json,
    backup_sqlite,
    choose_canonical_username,
    migrate_local_device_json,
    migrate_local_session_json,
    migrate_manager_state_identity,
    postgres_identity_plan,
    sqlite_identity_plan,
    user_root_identity_plan,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=Path(settings.CACHE_DB_PATH))
    parser.add_argument("--control-settings", type=Path, default=None)
    parser.add_argument("--postgres-url", default="")
    parser.add_argument("--old-username", default="18717974771")
    parser.add_argument("--organization", default="GTHT")
    parser.add_argument("--alias", default="MaxJJW")
    parser.add_argument("--new-username", default="")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument(
        "--postgres-backup-file",
        type=Path,
        default=None,
        help="pre-created pg_dump custom-format file; skips running pg_dump",
    )
    parser.add_argument(
        "--postgres-dump-ssh-host",
        default=os.environ.get("FACTORTESTER_POSTGRES_DUMP_SSH_HOST", ""),
        help="SSH host alias whose PostgreSQL container owns pg_dump",
    )
    parser.add_argument(
        "--postgres-dump-container",
        default=os.environ.get("FACTORTESTER_POSTGRES_DUMP_CONTAINER", ""),
        help="remote Docker container used with --postgres-dump-ssh-host",
    )
    parser.add_argument(
        "--state-root", type=Path, action="append", default=[],
        help="Manager state directory; may be supplied more than once",
    )
    parser.add_argument(
        "--user-root-parent", type=Path, action="append", default=[],
        help="Principal workspace parent; may be supplied more than once",
    )
    parser.add_argument("--local-device-file", action="append", default=[])
    parser.add_argument("--delete-other-users", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser


def _control_url(args: argparse.Namespace) -> str:
    if args.postgres_url:
        return str(args.postgres_url).strip()
    environment_url = str(
        os.environ.get("FACTORTESTER_CONTROL_DATABASE_URL") or ""
    ).strip()
    if environment_url:
        return environment_url
    if args.control_settings is None:
        return ""
    try:
        value = json.loads(args.control_settings.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("control database settings cannot be read") from exc
    return str(value.get("url") or "").strip() if isinstance(value, dict) else ""


def _new_username(args: argparse.Namespace, accounts: list[dict[str, object]]) -> str:
    if args.new_username:
        value = str(args.new_username).strip()
        # Re-parse through the canonical constructor so the migration cannot
        # accidentally write a legacy ``organization$alias@serial`` value.
        parts = value.split("@")
        if len(parts) != 3:
            raise ValueError("--new-username must be organization@alias@numeric-suffix")
        return canonical_username(parts[0], parts[1], parts[2])
    return choose_canonical_username(accounts, args.organization, args.alias)


def _manifest_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**value, "plan_hash": _manifest_hash(value)}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("migration manifest must be an object")
    expected = str(value.pop("plan_hash") or "")
    if expected != _manifest_hash(value):
        raise ValueError("migration manifest hash does not match its contents")
    return value


def _backup_postgres(
    url: str,
    destination: Path,
    *,
    ssh_host: str = "",
    container: str = "",
    existing_backup: Path | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if existing_backup is not None:
        source = existing_backup.expanduser().resolve()
        if not source.is_file() or source.stat().st_size < 128:
            raise RuntimeError("the pre-created PostgreSQL backup is missing or too small")
        if source != destination.resolve():
            shutil.copy2(source, destination)
        if destination.stat().st_size < 128:
            raise RuntimeError("the PostgreSQL backup copy is unexpectedly small")
        return
    if ssh_host:
        if not container or not re.fullmatch(r"[A-Za-z0-9_.-]+", container):
            raise RuntimeError(
                "a safe --postgres-dump-container is required with "
                "--postgres-dump-ssh-host"
            )
        parsed = urlsplit(url)
        database = unquote(parsed.path.lstrip("/"))
        user = unquote(parsed.username or "")
        if not database or not user:
            raise RuntimeError(
                "PostgreSQL URL must include database and user for remote pg_dump"
            )
        remote = shlex.join([
            "docker", "exec", container, "pg_dump",
            "--format=custom",
            "--dbname", database,
            "--username", user,
        ])
        command = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15",
            ssh_host,
            remote,
        ]
        try:
            with destination.open("wb") as output:
                subprocess.run(
                    command,
                    check=True,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=180,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                "remote pg_dump failed; no account deletion was performed"
            ) from exc
        if destination.stat().st_size < 128:
            raise RuntimeError(
                "remote pg_dump produced an unexpectedly small backup"
            )
        return
    try:
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(destination), url],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "pg_dump failed; no account deletion was performed"
        ) from exc


def _connect_postgres(url: str):
    if not url:
        return None
    try:
        import psycopg

        return psycopg.connect(
            url,
            connect_timeout=5,
        )
    except ImportError as exc:
        raise RuntimeError("psycopg is required in the GTHT environment") from exc


def _postgres_failure_status(exc: Exception) -> str:
    """Distinguish network failure from a reachable-but-invalid schema."""
    try:
        import psycopg
    except ImportError:
        return "error"
    if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        return "unavailable"
    return "query_error"


def _local_device_files(args: argparse.Namespace) -> list[Path]:
    values = [Path(item).expanduser().resolve() for item in args.local_device_file]
    for state_root in args.state_root:
        root = state_root.expanduser().resolve()
        values.extend([
            root / "device-registry.json",
            root / "device-authorizations.json",
            root / "sessions.json",
        ])
    return list(dict.fromkeys(values))


def _build_plan(args: argparse.Namespace) -> tuple[dict[str, object], str]:
    database = args.sqlite.expanduser().resolve()
    local_accounts = []
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        local_accounts = [dict(row) for row in connection.execute(
            "SELECT username, alias, organization_id FROM accounts ORDER BY username"
        ).fetchall()]
    new_username = _new_username(args, local_accounts)
    local = sqlite_identity_plan(
        database,
        old_username=args.old_username,
        new_username=new_username,
        organization_id=args.organization,
        alias=args.alias,
    )
    central: dict[str, object] = {"status": "not_configured"}
    url = _control_url(args)
    if url:
        try:
            with _connect_postgres(url) as connection:
                central = {"status": "reachable", **postgres_identity_plan(
                    connection, old_username=args.old_username,
                )}
        except Exception as exc:
            central = {
                "status": _postgres_failure_status(exc),
                "error_type": type(exc).__name__,
            }
    plan = {
        "schema_version": 1,
        "created_at": int(time.time()),
        "old_username": args.old_username,
        "new_username": new_username,
        "organization_id": args.organization,
        "organization_name": "GTHT" if args.organization == "GTHT" else args.organization,
        "alias": args.alias,
        "delete_other_users": bool(args.delete_other_users),
        "sqlite": local,
        "postgresql": central,
        "local_device_files": [str(path) for path in _local_device_files(args)],
        "user_root_parents": [
            user_root_identity_plan(
                parent,
                old_username=args.old_username,
                new_username=new_username,
            )
            for parent in args.user_root_parent
        ],
    }
    return plan, new_username


def _apply(args: argparse.Namespace, plan: dict[str, object]) -> None:
    if not args.delete_other_users or not bool(plan.get("delete_other_users")):
        raise RuntimeError("--apply requires --delete-other-users in the dry-run manifest")
    if plan.get("postgresql", {}).get("status") != "reachable":
        raise RuntimeError("PostgreSQL was not reachable when the manifest was created")
    sqlite_plan = plan.get("sqlite")
    if not isinstance(sqlite_plan, dict):
        raise RuntimeError("migration manifest has no SQLite plan")
    sqlite_path = args.sqlite.expanduser().resolve()
    planned_path = str(sqlite_plan.get("database") or "")
    if planned_path and sqlite_path != Path(planned_path).expanduser().resolve():
        raise RuntimeError(
            "the current SQLite path differs from the dry-run manifest"
        )
    backup_root = (
        args.backup_dir.expanduser().resolve()
        if args.backup_dir
        else args.manifest.expanduser().resolve().with_suffix("")
    )
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_sqlite(sqlite_path, backup_root / "unifieddata.sqlite")
    device_files = [Path(item) for item in plan.get("local_device_files") or []]
    for index, path in enumerate(device_files, start=1):
        backup_json(
            path,
            backup_root / "local-state" / f"{index:02d}-{path.name}",
        )
    url = _control_url(args)
    if not url:
        raise RuntimeError("PostgreSQL URL is required for apply")
    _backup_postgres(
        url,
        backup_root / "control.dump",
        ssh_host=str(args.postgres_dump_ssh_host or "").strip(),
        container=str(args.postgres_dump_container or "").strip(),
        existing_backup=args.postgres_backup_file,
    )

    with _connect_postgres(url) as connection:
        apply_postgres_identity_migration(
            connection,
            old_username=str(plan["old_username"]),
            new_username=str(plan["new_username"]),
            organization_id=str(plan["organization_id"]),
            organization_name=str(plan["organization_name"]),
            alias=str(plan["alias"]),
        )
    counts = apply_sqlite_identity_migration(
        sqlite_path,
        old_username=str(plan["old_username"]),
        new_username=str(plan["new_username"]),
        organization_id=str(plan["organization_id"]),
        organization_name=str(plan["organization_name"]),
        alias=str(plan["alias"]),
    )
    state_counts: dict[str, dict[str, int]] = {}
    for path in device_files:
        migration = (
            migrate_local_session_json
            if path.name == "sessions.json"
            else migrate_local_device_json
        )
        state_counts[str(path)] = migration(
            path,
            old_username=str(plan["old_username"]),
            new_username=str(plan["new_username"]),
        )
    for state_root in args.state_root:
        root = state_root.expanduser().resolve()
        state_counts[str(root)] = migrate_manager_state_identity(
            root,
            old_username=str(plan["old_username"]),
            new_username=str(plan["new_username"]),
        )
    root_counts: dict[str, dict[str, int]] = {}
    for item in plan.get("user_root_parents") or []:
        if not isinstance(item, dict):
            raise RuntimeError("migration manifest has an invalid user-root plan")
        parent = str(item.get("parent") or "")
        if not parent:
            raise RuntimeError("migration manifest has an empty user-root parent")
        root_counts[parent] = apply_user_root_identity_migration(
            parent,
            old_username=str(plan["old_username"]),
            new_username=str(plan["new_username"]),
            backup_root=backup_root,
        )
    print(json.dumps({
        "applied": True,
        "sqlite": counts,
        "local_state": state_counts,
        "user_roots": root_counts,
    }, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.apply:
            plan = _read_manifest(args.manifest)
            _apply(args, plan)
        else:
            plan, new_username = _build_plan(args)
            _write_manifest(args.manifest, plan)
            print(json.dumps({
                "dry_run": True,
                "manifest": str(args.manifest.expanduser().resolve()),
                "new_username": new_username,
                "postgresql_status": plan["postgresql"]["status"],
                "sqlite_other_accounts": plan["sqlite"]["other_account_count"],
            }, ensure_ascii=False))
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

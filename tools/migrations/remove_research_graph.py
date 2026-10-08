"""Backed-up, one-shot removal of Research Graph storage.

Run the dry-run against an offline Manager SQLite database and the exact local
``research-graphs`` directory first.  Apply creates independent database and
file backups, removes Graph-only state, migrates Job assurance receipts into
the existing Job owner, and verifies that ordinary Research/Report/Run/Job/
Evidence records retain their content and stable references.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
from typing import Any

from server.services.backend_assurance_migration import (
    migrate_backend_assurance_in_transaction,
)
from server.services.research_run_schema import (
    _RETIRED_INDEXES,
    _RETIRED_RUN_COLUMNS,
)
from tools.data.sqlite.db import connect_sqlite


# These are Graph-owned tables from both the final schema and its old control
# plane.  Shared Evidence admissions, Maintenance Cases, and Job assurance
# receipts are deliberately handled separately below.
GRAPH_TABLES = frozenset({
    "active_research_graphs",
    "user_research_graphs",
    "user_research_graph_preferences",
    "research_graph_versions",
    "research_graph_instances",
    "research_graph_branches",
    "research_graph_trace",
    "research_graph_objects",
    "research_graph_presentations",
    "research_graph_capability_detours",
    "research_work_packages",
    "research_report_item_checkpoints",
    "research_report_item_checkpoints_next",
    "research_human_gate_overrides",
    "research_evidence_lifecycle_transitions",
    "trial_plan_action_adjudication_receipts",
    "research_agent_executions",
    "research_graph_validations",
    "research_graph_proposals",
    "research_graph_reviews",
    "research_graph_audits",
    "human_activation_authorizations",
    "research_capability_approvals",
    "research_graph_server_secrets",
    "research_graph_node_resolutions",
    "research_capability_receipts",
    "research_graph_rollbacks",
})

_GRAPH_REF_PREFIXES = (
    "graph-branch:",
    "graph-instance:",
    "graph-version-delta:",
    "graph-object:",
    "graph-node:",
    "graph-edge:",
    "research-graph:",
    "work-package:",
)
_GRAPH_TABLE_PREFIXES = (
    "research_graph_",
    "active_research_graph",
    "user_research_graph",
    "research_report_item_checkpoint",
    "research_work_package",
    "research_agent_execution",
    "research_capability_",
    "human_activation_authorization",
)
_PRESERVED_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "research_catalog_researches": (),
    "research_catalog_reports": (),
    "research_catalog_branches": (),
    "research_catalog_report_evidence_links": ("graph_ref",),
    "research_workspaces": (),
    "research_configurations": (),
    "research_configuration_snapshots": (),
    "research_runs": tuple(_RETIRED_RUN_COLUMNS),
    # The existing assurance migration intentionally fills these two fields.
    "research_jobs": ("run_spec_hash", "terminal_assurance_json"),
    "research_job_subjects": (),
    "research_job_subject_index_state": (),
    "research_job_artifacts": (),
    "research_job_custom_analyses": (),
    "research_evidence_objects": (),
    "research_evidence_sources": (),
    "research_evidence_fragments": (),
    "research_fragment_evidence_objects": (),
    "research_evidence_catalog_state": (),
    "research_evidence_tags": (),
    "research_evidence_tag_proposals": (),
    "research_evidence_object_tags": (),
    "research_evidence_lifecycle": (),
    "research_evidence_status_events": (),
}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row[1])
        for row in conn.execute(f'PRAGMA table_info("{table}")')
    ]


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _safe_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if value is None or isinstance(value, (str, int, float)):
        return value
    return {"type": type(value).__name__, "repr": repr(value)}


def _content_fingerprint(
    conn: sqlite3.Connection,
    table: str,
    *,
    exclude_columns: tuple[str, ...] = (),
    where: str = "",
    params: tuple[Any, ...] = (),
) -> dict[str, Any]:
    columns = [column for column in _columns(conn, table) if column not in exclude_columns]
    if not columns:
        return {"count": 0, "columns": [], "content_hash": hashlib.sha256(b"").hexdigest()}
    info = conn.execute(f'PRAGMA table_info({_quote(table)})').fetchall()
    primary = [
        str(row[1]) for row in sorted(info, key=lambda item: int(item[5]) or 10**6)
        if int(row[5]) > 0 and str(row[1]) in columns
    ]
    order = primary or columns
    sql = (
        f"SELECT {', '.join(_quote(column) for column in columns)} "
        f"FROM {_quote(table)}"
        + (f" WHERE {where}" if where else "")
        + f" ORDER BY {', '.join(_quote(column) for column in order)}"
    )
    digest = hashlib.sha256()
    count = 0
    cursor = conn.execute(sql, params)
    for row in cursor:
        encoded = json.dumps(
            [_safe_value(value) for value in row],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
        count += 1
    return {"count": count, "columns": columns, "content_hash": digest.hexdigest()}


def _key_fingerprint(
    conn: sqlite3.Connection, table: str, key: str,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    for row in conn.execute(
        f"SELECT {_quote(key)} FROM {_quote(table)} ORDER BY {_quote(key)}"
    ):
        digest.update(json.dumps(row[0], ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return {"count": count, "ref_hash": digest.hexdigest()}


def _key_values(
    conn: sqlite3.Connection, table: str, key: str,
) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            f"SELECT {_quote(key)} FROM {_quote(table)}"
        )
    }


def _graph_ref_where(column: str) -> tuple[str, tuple[str, ...]]:
    clauses = [f"substr({_quote(column)}, 1, length(?)) = ?" for _ in _GRAPH_REF_PREFIXES]
    params = tuple(value for prefix in _GRAPH_REF_PREFIXES for value in (prefix, prefix))
    return "(" + " OR ".join(clauses) + ")", params


def _database_fingerprint(conn: sqlite3.Connection) -> dict[str, Any]:
    """Fingerprint every table and schema object before trusting a DB backup."""
    schema = [
        [str(row[0]), str(row[1]), str(row[2] or "")]
        for row in conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    ]
    tables = {}
    for table in sorted(_tables(conn)):
        tables[table] = _content_fingerprint(conn, table)
    encoded = json.dumps(
        {"schema": schema, "tables": tables},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "tables": tables}


def _unknown_graph_tables(tables: set[str]) -> list[str]:
    return sorted(
        table for table in tables
        if table not in GRAPH_TABLES
        and any(table.startswith(prefix) for prefix in _GRAPH_TABLE_PREFIXES)
    )


def _unknown_graph_columns(
    conn: sqlite3.Connection, tables: set[str],
) -> list[dict[str, str]]:
    retired_run_columns = set(_RETIRED_RUN_COLUMNS)
    values = []
    for table in sorted(tables - GRAPH_TABLES):
        for column in _columns(conn, table):
            lowered = column.lower()
            if "graph" not in lowered and "work_package" not in lowered:
                continue
            if table == "research_backend_assurance_receipts":
                # The existing Job cutover validates and moves these legacy
                # attestation fields into the canonical terminal Job record.
                continue
            if table == "research_runs" and column in retired_run_columns:
                continue
            if (
                table == "research_catalog_report_evidence_links"
                and column == "graph_ref"
            ):
                continue
            values.append({"table": table, "column": column})
    return values


def _external_graph_foreign_keys(
    conn: sqlite3.Connection, tables: set[str],
) -> list[dict[str, str]]:
    references = []
    for table in sorted(tables - GRAPH_TABLES):
        for row in conn.execute(f"PRAGMA foreign_key_list({_quote(table)})"):
            parent = str(row[2])
            if parent in GRAPH_TABLES:
                references.append({
                    "table": table,
                    "column": str(row[3]),
                    "parent_table": parent,
                    "parent_column": str(row[4]),
                })
    return references


def _is_graph_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_GRAPH_REF_PREFIXES)


def _maintenance_graph_ref_report(conn: sqlite3.Connection, tables: set[str]) -> dict[str, Any]:
    table = "research_maintenance_cases"
    if table not in tables:
        return {"cases": 0, "refs": 0, "unclassified_rows": 0}
    columns = set(_columns(conn, table))
    required = {"case_id", "affected_refs_json", "change_refs_json"}
    if not required <= columns:
        return {"cases": 0, "refs": 0, "unclassified_rows": 1}
    cases = refs = unclassified_rows = 0
    for row in conn.execute(
        f"SELECT case_id, affected_refs_json, change_refs_json FROM {_quote(table)}"
    ):
        found = False
        for raw in (row[1], row[2]):
            try:
                values = json.loads(str(raw))
            except (TypeError, ValueError):
                unclassified_rows += 1
                continue
            if not isinstance(values, list):
                unclassified_rows += 1
                continue
            for value in values:
                if _is_graph_ref(value):
                    refs += 1
                    found = True
                elif isinstance(value, str) and (
                    "graph" in value.lower() or "work-package:" in value.lower()
                ):
                    unclassified_rows += 1
        if found:
            cases += 1
    return {"cases": cases, "refs": refs, "unclassified_rows": unclassified_rows}


def _graph_admission_count(conn: sqlite3.Connection, tables: set[str]) -> int:
    table = "research_evidence_admissions"
    if table not in tables or "subject_ref" not in _columns(conn, table):
        return 0
    where, params = _graph_ref_where("subject_ref")
    return int(conn.execute(
        f"SELECT COUNT(*) FROM {_quote(table)} WHERE {where}", params,
    ).fetchone()[0])


def _nonempty_value_count(
    conn: sqlite3.Connection, table: str, column: str,
) -> int:
    if table not in _tables(conn) or column not in _columns(conn, table):
        return 0
    return int(conn.execute(
        f"SELECT COUNT(*) FROM {_quote(table)} WHERE "
        f"{_quote(column)} IS NOT NULL AND CAST({_quote(column)} AS TEXT) <> ''"
    ).fetchone()[0])


def _graph_files_inventory(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "state": "not_configured", "file_count": 0, "bytes": 0,
            "files": [], "directories": [], "root_metadata": None,
        }
    supplied = Path(path).expanduser()
    if supplied.name != "research-graphs":
        raise ValueError("--graph-files must point to the exact research-graphs directory")
    if supplied.is_symlink():
        raise ValueError("Graph files directory must not be a symbolic link")
    root = supplied.resolve(strict=False)
    if not root.exists():
        return {
            "state": "absent", "path": str(root), "file_count": 0,
            "bytes": 0, "files": [], "directories": [],
            "root_metadata": None,
        }
    if not root.is_dir():
        raise ValueError("Graph files path is not a directory")
    entries = []
    directories = []
    total_bytes = 0
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError("Graph files directory contains a symbolic link")
        metadata = item.stat()
        if item.is_dir():
            directories.append({
                "path": item.relative_to(root).as_posix(),
                "mode": stat.S_IMODE(metadata.st_mode),
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
            })
            continue
        if not item.is_file():
            continue
        digest = hashlib.sha256()
        size = 0
        with item.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        total_bytes += size
        entries.append({
            "path": item.relative_to(root).as_posix(),
            "bytes": size,
            "sha256": digest.hexdigest(),
            "mode": stat.S_IMODE(metadata.st_mode),
            "uid": metadata.st_uid,
            "gid": metadata.st_gid,
        })
    return {
        "state": "present",
        "path": str(root),
        "file_count": len(entries),
        "bytes": total_bytes,
        "files": entries,
        "directories": directories,
        "root_metadata": {
            "mode": stat.S_IMODE(root.stat().st_mode),
            "uid": root.stat().st_uid,
            "gid": root.stat().st_gid,
        },
    }


def inspect(
    conn: sqlite3.Connection,
    *,
    graph_files: Path | None = None,
) -> dict[str, Any]:
    tables = _tables(conn)
    unknown = _unknown_graph_tables(tables)
    graph_admissions = _graph_admission_count(conn, tables)
    maintenance = _maintenance_graph_ref_report(conn, tables)
    preserved = {
        table: _content_fingerprint(
            conn,
            table,
            exclude_columns=excluded,
            where=(
                "subject_ref NOT LIKE 'graph-branch:%'"
                if table == "research_evidence_admissions" else ""
            ),
        )
        for table, excluded in _PRESERVED_TABLE_COLUMNS.items()
        if table in tables
    }
    if "research_evidence_admissions" in tables:
        graph_where, graph_params = _graph_ref_where("subject_ref")
        preserved["research_evidence_admissions"] = _content_fingerprint(
            conn,
            "research_evidence_admissions",
            where=f"(subject_ref IS NULL OR NOT {graph_where})",
            params=graph_params,
        )
    report = {
        "graph_tables": {
            table: int(conn.execute(
                f"SELECT COUNT(*) FROM {_quote(table)}"
            ).fetchone()[0])
            for table in sorted(tables & GRAPH_TABLES)
        },
        "legacy_backend_receipts": (
            int(conn.execute(
                "SELECT COUNT(*) FROM research_backend_assurance_receipts"
            ).fetchone()[0])
            if "research_backend_assurance_receipts" in tables else 0
        ),
        "graph_evidence_admissions": graph_admissions,
        "maintenance_graph_refs": maintenance,
        "unknown_graph_tables": unknown,
        "unknown_graph_columns": _unknown_graph_columns(conn, tables),
        "external_graph_foreign_keys": _external_graph_foreign_keys(conn, tables),
        "run_columns": sorted(
            set(_columns(conn, "research_runs")) & set(_RETIRED_RUN_COLUMNS)
        ) if "research_runs" in tables else [],
        "run_retired_column_values": {
            column: _nonempty_value_count(conn, "research_runs", column)
            for column in sorted(
                set(_columns(conn, "research_runs")) & set(_RETIRED_RUN_COLUMNS)
            )
        } if "research_runs" in tables else {},
        "report_evidence_graph_column": (
            "research_catalog_report_evidence_links" in tables
            and "graph_ref" in _columns(conn, "research_catalog_report_evidence_links")
        ),
        "report_evidence_graph_ref_values": _nonempty_value_count(
            conn, "research_catalog_report_evidence_links", "graph_ref",
        ),
        "preserved": preserved,
        "maintenance_case_ids": (
            _key_fingerprint(conn, "research_maintenance_cases", "case_id")
            if "research_maintenance_cases" in tables else {"count": 0, "ref_hash": hashlib.sha256(b"").hexdigest()}
        ),
        "graph_files": _graph_files_inventory(graph_files),
    }
    report["blockers"] = _readiness_blockers(report)
    report["ready_to_apply"] = not report["blockers"]
    return report


def _readiness_blockers(report: dict[str, Any]) -> list[str]:
    blockers = []
    if report["unknown_graph_tables"]:
        blockers.append(
            "unknown Graph tables: " + ", ".join(report["unknown_graph_tables"])
        )
    if report["unknown_graph_columns"]:
        blockers.append(
            "unknown Graph columns: "
            + json.dumps(report["unknown_graph_columns"], ensure_ascii=False)
        )
    if report["external_graph_foreign_keys"]:
        blockers.append("external foreign keys target Graph tables")
    if report["maintenance_graph_refs"]["unclassified_rows"]:
        blockers.append("Maintenance Case Graph references need manual classification")
    return blockers


def _remove_evidence_graph_column(conn: sqlite3.Connection) -> None:
    table = "research_catalog_report_evidence_links"
    if table not in _tables(conn) or "graph_ref" not in _columns(conn, table):
        return
    legacy = f"{table}_graph_legacy"
    if legacy in _tables(conn):
        raise RuntimeError("incomplete earlier Report-Evidence migration")
    conn.execute("DROP INDEX IF EXISTS idx_research_catalog_evidence")
    conn.execute(f"ALTER TABLE {_quote(table)} RENAME TO {_quote(legacy)}")
    conn.execute(f"""
        CREATE TABLE {_quote(table)} (
            link_ref TEXT PRIMARY KEY,
            evidence_ref TEXT NOT NULL,
            evidence_owner_ref TEXT NOT NULL,
            report_id TEXT NOT NULL,
            branch_ref TEXT NOT NULL,
            job_id TEXT NOT NULL,
            profile_ref TEXT NOT NULL,
            purpose TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            revoked_at REAL NOT NULL,
            FOREIGN KEY(report_id) REFERENCES research_catalog_reports(report_id)
        )
    """)
    columns = (
        "link_ref, evidence_ref, evidence_owner_ref, report_id, branch_ref, "
        "job_id, profile_ref, purpose, status, created_at, revoked_at"
    )
    conn.execute(
        f"INSERT INTO {_quote(table)} ({columns}) "
        f"SELECT {columns} FROM {_quote(legacy)}"
    )
    conn.execute(f"DROP TABLE {_quote(legacy)}")
    conn.execute(
        "CREATE INDEX idx_research_catalog_evidence "
        "ON research_catalog_report_evidence_links(evidence_ref, status)"
    )


def _strip_maintenance_graph_refs(conn: sqlite3.Connection) -> int:
    table = "research_maintenance_cases"
    if table not in _tables(conn):
        return 0
    removed = 0
    for row in conn.execute(
        f"SELECT case_id, affected_refs_json, change_refs_json FROM {_quote(table)}"
    ).fetchall():
        updates = {}
        for field in ("affected_refs_json", "change_refs_json"):
            values = json.loads(str(row[field]))
            remaining = [value for value in values if not _is_graph_ref(value)]
            removed += len(values) - len(remaining)
            if remaining != values:
                updates[field] = json.dumps(
                    remaining, ensure_ascii=False, separators=(",", ":"),
                )
        for field, value in updates.items():
            conn.execute(
                f"UPDATE {_quote(table)} SET {_quote(field)}=? WHERE case_id=?",
                (value, row["case_id"]),
            )
    return removed


def _assert_ready(before: dict[str, Any]) -> None:
    errors = _readiness_blockers(before)
    if errors:
        raise RuntimeError("; ".join(errors))


def _validate_file_backup_paths(
    graph_files: Path,
    files_backup: Path | None,
    database: Path,
    database_backup: Path,
) -> tuple[Path, Path | None]:
    inventory = _graph_files_inventory(graph_files)
    root = Path(inventory.get("path") or graph_files.expanduser().resolve())
    if inventory["state"] != "absent" and files_backup is None:
        raise ValueError("--files-backup is required when Graph files exist")
    if files_backup is None:
        return root, None
    backup = Path(files_backup).expanduser().resolve(strict=False)
    manifest = _file_backup_manifest_path(backup)
    if backup.exists() or manifest.exists():
        raise FileExistsError("Graph file backup already exists")
    if backup in {database, database_backup} or manifest in {database, database_backup}:
        raise ValueError("file backup must be separate from the database and its backup")
    if backup == root or root in backup.parents or backup in root.parents:
        raise ValueError("file backup must be outside the Graph files directory")
    return root, backup


def _file_backup_manifest_path(backup: Path) -> Path:
    return Path(f"{backup}.manifest.json")


def _write_file_backup_manifest(
    backup: Path,
    *,
    state: str,
    inventory: dict[str, Any],
) -> Path:
    manifest = _file_backup_manifest_path(backup)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": 1,
        "state": state,
        "file_count": int(inventory["file_count"]),
        "bytes": int(inventory["bytes"]),
        "files": inventory["files"],
        "directories": inventory["directories"],
        "root_metadata": inventory["root_metadata"],
    }
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(manifest, 0o600)
    return manifest


def _manifest_inventory(manifest: Path) -> dict[str, Any]:
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError("Graph file backup manifest is unavailable")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Graph file backup manifest is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("format") != 1
        or payload.get("state") not in {"absent", "present"}
        or not isinstance(payload.get("files"), list)
        or not isinstance(payload.get("directories"), list)
    ):
        raise RuntimeError("Graph file backup manifest is invalid")
    files = payload["files"]
    directories = payload["directories"]

    def safe_relative_path(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        relative = PurePosixPath(value)
        return (
            not relative.is_absolute()
            and "\\" not in value
            and bool(relative.parts)
            and all(part not in {"", ".", ".."} for part in relative.parts)
        )

    def valid_metadata(item: Any) -> bool:
        return (
            isinstance(item, dict)
            and all(isinstance(item.get(key), int) and item[key] >= 0
                    for key in ("mode", "uid", "gid"))
        )

    if any(
        not isinstance(item, dict)
        or not safe_relative_path(item.get("path"))
        or not isinstance(item.get("bytes"), int)
        or item["bytes"] < 0
        or not isinstance(item.get("sha256"), str)
        or len(item["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in item["sha256"])
        or not valid_metadata(item)
        for item in files
    ) or any(
        not isinstance(item, dict)
        or not safe_relative_path(item.get("path"))
        or not valid_metadata(item)
        for item in directories
    ):
        raise RuntimeError("Graph file backup manifest is invalid")
    paths = [str(item["path"]) for item in [*files, *directories]]
    if len(paths) != len(set(paths)):
        raise RuntimeError("Graph file backup manifest contains duplicate paths")
    if int(payload.get("file_count", -1)) != len(files):
        raise RuntimeError("Graph file backup manifest count is invalid")
    if int(payload.get("bytes", -1)) != sum(int(item["bytes"]) for item in files):
        raise RuntimeError("Graph file backup manifest size is invalid")
    if payload["state"] == "absent" and (
        files or payload["directories"] or payload.get("root_metadata") is not None
    ):
        raise RuntimeError("absent Graph file backup manifest contains file entries")
    if payload["state"] == "present" and not valid_metadata(
        payload.get("root_metadata"),
    ):
        raise RuntimeError("Graph file backup manifest root metadata is invalid")
    return payload


def _restore_owner_mode(path: Path, metadata: dict[str, Any]) -> None:
    uid, gid = int(metadata["uid"]), int(metadata["gid"])
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        current = path.stat()
        if current.st_uid != uid or current.st_gid != gid:
            raise
    os.chmod(path, int(metadata["mode"]))


def _restore_graph_file_metadata(root: Path, inventory: dict[str, Any]) -> None:
    for item in inventory["files"]:
        _restore_owner_mode(root / str(item["path"]), item)
    for item in sorted(
        inventory["directories"],
        key=lambda entry: str(entry["path"]).count("/"),
        reverse=True,
    ):
        _restore_owner_mode(root / str(item["path"]), item)
    root_metadata = inventory.get("root_metadata")
    if isinstance(root_metadata, dict):
        _restore_owner_mode(root, root_metadata)


def _verify_file_backup(inventory: dict[str, Any], backup: Path) -> bool:
    expected = {
        item["path"]: (int(item["bytes"]), str(item["sha256"]))
        for item in inventory["files"]
    }
    actual: dict[str, tuple[int, str]] = {}
    actual_directories: set[str] = set()
    if not backup.is_dir():
        return False
    for item in sorted(backup.rglob("*")):
        if item.is_symlink():
            return False
        if item.is_dir():
            actual_directories.add(item.relative_to(backup).as_posix())
            continue
        if not item.is_file():
            continue
        digest = hashlib.sha256()
        size = 0
        with item.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        actual[item.relative_to(backup).as_posix()] = (size, digest.hexdigest())
    expected_directories = {
        str(item["path"]) for item in inventory.get("directories", [])
    }
    return actual == expected and actual_directories == expected_directories


def apply(
    database: Path,
    backup: Path,
    *,
    graph_files: Path,
    files_backup: Path | None = None,
) -> dict[str, Any]:
    database = Path(database).expanduser().resolve()
    backup = Path(backup).expanduser().resolve(strict=False)
    if not database.is_file():
        raise FileNotFoundError(f"database does not exist: {database}")
    if backup.exists():
        raise FileExistsError(f"backup already exists: {backup}")
    files_root, files_backup_path = _validate_file_backup_paths(
        graph_files, files_backup, database, backup,
    )
    with connect_sqlite(database, readonly=True) as preflight_conn:
        preflight = inspect(preflight_conn, graph_files=files_root)
        _assert_ready(preflight)
    backup.parent.mkdir(parents=True, exist_ok=True)
    staging = files_root.with_name(f".{files_root.name}.cutover-staging")
    if staging.exists():
        raise FileExistsError(f"stale Graph file staging directory exists: {staging}")

    with connect_sqlite(database, readonly=True) as source, connect_sqlite(backup) as target:
        source.backup(target)
    backup_verified = False
    with connect_sqlite(backup, readonly=True) as backup_conn:
        with connect_sqlite(database, readonly=True) as source_conn:
            backup_verified = _database_fingerprint(source_conn) == _database_fingerprint(backup_conn)
    if not backup_verified:
        raise RuntimeError("database backup verification failed")

    files_manifest = None
    if files_backup_path is not None:
        files_backup_path.parent.mkdir(parents=True, exist_ok=True)
        if preflight["graph_files"]["state"] == "present":
            shutil.copytree(files_root, files_backup_path, copy_function=shutil.copy2)
            if not _verify_file_backup(preflight["graph_files"], files_backup_path):
                raise RuntimeError("Graph files backup verification failed")
        files_manifest = _write_file_backup_manifest(
            files_backup_path,
            state=str(preflight["graph_files"]["state"]),
            inventory=preflight["graph_files"],
        )
    staged = False
    removed_staging = False
    try:
        with connect_sqlite(database) as conn:
            before = inspect(conn, graph_files=files_root)
            _assert_ready(before)
            before_case_ids = _key_values(
                conn, "research_maintenance_cases", "case_id",
            ) if "research_maintenance_cases" in _tables(conn) else set()
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("BEGIN IMMEDIATE")

            assurance_migration = None
            if "research_backend_assurance_receipts" in _tables(conn):
                assurance_migration = migrate_backend_assurance_in_transaction(conn)

            graph_admissions_removed = 0
            if "research_evidence_admissions" in _tables(conn):
                graph_where, graph_params = _graph_ref_where("subject_ref")
                graph_admissions_removed = conn.execute(
                    f"DELETE FROM research_evidence_admissions WHERE {graph_where}",
                    graph_params,
                ).rowcount
            maintenance_refs_removed = _strip_maintenance_graph_refs(conn)

            for table in sorted(before["graph_tables"]):
                conn.execute(f"DROP TABLE {_quote(table)}")
            if "research_runs" in _tables(conn):
                for index in _RETIRED_INDEXES:
                    conn.execute(f"DROP INDEX IF EXISTS {_quote(index)}")
                for column in before["run_columns"]:
                    conn.execute(
                        f"ALTER TABLE research_runs DROP COLUMN {_quote(column)}"
                    )
            _remove_evidence_graph_column(conn)

            if (
                files_backup_path is not None
                and before["graph_files"]["state"] == "present"
            ):
                os.replace(files_root, staging)
                staged = True
                shutil.rmtree(staging)
                removed_staging = True

            after = inspect(conn, graph_files=files_root)
            if before["preserved"] != after["preserved"]:
                raise RuntimeError("preserved Research/Report/Run/Job/Evidence content changed")
            after_case_ids = _key_values(
                conn, "research_maintenance_cases", "case_id",
            ) if "research_maintenance_cases" in _tables(conn) else set()
            if not before_case_ids.issubset(after_case_ids):
                raise RuntimeError("existing Maintenance Case identities changed")
            if after["graph_tables"] or after["run_columns"] or after["report_evidence_graph_column"]:
                raise RuntimeError("Graph schema remains after migration")
            if after["graph_evidence_admissions"] or after["maintenance_graph_refs"]["refs"]:
                raise RuntimeError("Graph references remain in shared records")
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("foreign-key check failed after Graph removal")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity check failed after Graph removal")
            conn.commit()
            return {
                "backup": str(backup),
                "files_backup": str(files_backup_path) if files_backup_path else None,
                "files_manifest": str(files_manifest) if files_manifest else None,
                "assurance_migration": assurance_migration,
                "graph_evidence_admissions_removed": graph_admissions_removed,
                "maintenance_graph_refs_removed": maintenance_refs_removed,
                "before": before,
                "after": after,
            }
    except Exception:
        if staged:
            if staging.exists():
                os.replace(staging, files_root)
            elif removed_staging and files_backup_path is not None:
                shutil.copytree(files_backup_path, files_root, copy_function=shutil.copy2)
                if files_manifest is not None:
                    _restore_graph_file_metadata(
                        files_root, _manifest_inventory(files_manifest),
                    )
        raise


def restore_backup(
    database: Path,
    backup: Path,
    *,
    graph_files: Path,
    files_backup: Path | None = None,
) -> dict[str, Any]:
    """Restore the verified pre-cutover SQLite and Graph-file backups offline.

    The database is staged and verified beside the live file, then atomically
    replaced. A Graph file tree is also staged and verified from its manifest;
    failures before the database swap put the current tree back in place.
    Callers must stop the application before invoking this function.
    """
    database_input = Path(database).expanduser()
    backup_input = Path(backup).expanduser()
    graph_input = Path(graph_files).expanduser()
    if database_input.is_symlink() or backup_input.is_symlink() or graph_input.is_symlink():
        raise ValueError("SQLite and Graph rollback paths must not be symbolic links")
    database = database_input.resolve()
    backup = backup_input.resolve(strict=True)
    graph_root = graph_input.resolve(strict=False)
    if not database.is_file():
        raise FileNotFoundError("live database is unavailable or unsafe")
    if backup == database or not backup.is_file():
        raise ValueError("SQLite rollback backup is unavailable or unsafe")
    if graph_root.name != "research-graphs":
        raise ValueError("--graph-files must point to the exact research-graphs directory")
    if graph_root.is_symlink():
        raise ValueError("Graph files directory must not be a symbolic link")

    with connect_sqlite(backup, readonly=True) as source:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite rollback backup failed integrity check")
        if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("SQLite rollback backup failed foreign-key check")
        expected_fingerprint = _database_fingerprint(source)

    file_state: str | None = None
    file_manifest: Path | None = None
    files_backup_path: Path | None = None
    if files_backup is not None:
        files_backup_input = Path(files_backup).expanduser()
        if files_backup_input.is_symlink():
            raise ValueError("Graph file backup must not be a symbolic link")
        files_backup_path = files_backup_input.resolve(strict=False)
        file_manifest = _file_backup_manifest_path(files_backup_path)
        if file_manifest.exists():
            payload = _manifest_inventory(file_manifest)
            file_state = str(payload["state"])
            if file_state == "present":
                if not _verify_file_backup(payload, files_backup_path):
                    raise RuntimeError("Graph file rollback backup failed verification")
            elif files_backup_path.exists():
                raise RuntimeError("unexpected files exist for an absent Graph file backup")
        elif files_backup_path.exists():
            raise RuntimeError("Graph file rollback manifest is unavailable")

    database.parent.mkdir(parents=True, exist_ok=True)
    database_metadata = database.stat()
    fd, staging_name = tempfile.mkstemp(
        prefix=f".{database.name}.restore-", suffix=".tmp", dir=database.parent,
    )
    os.close(fd)
    database_staging = Path(staging_name)
    stage_root = graph_root.with_name(f".{graph_root.name}.restore-{os.getpid()}")
    displaced_root = graph_root.with_name(f".{graph_root.name}.displaced-{os.getpid()}")
    if stage_root.exists() or displaced_root.exists():
        database_staging.unlink(missing_ok=True)
        raise FileExistsError("stale Graph file rollback staging path exists")

    graph_tree_displaced = False
    graph_tree_installed = False
    database_replaced = False
    displaced_graph_files_retained = False
    try:
        with connect_sqlite(backup, readonly=True) as source, connect_sqlite(database_staging) as target:
            source.backup(target)
        with connect_sqlite(database_staging, readonly=True) as staged:
            if staged.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("staged SQLite rollback failed integrity check")
            if _database_fingerprint(staged) != expected_fingerprint:
                raise RuntimeError("staged SQLite rollback content does not match backup")
        try:
            os.chown(database_staging, database_metadata.st_uid, database_metadata.st_gid)
        except PermissionError:
            staged_owner = database_staging.stat()
            if (
                staged_owner.st_uid != database_metadata.st_uid
                or staged_owner.st_gid != database_metadata.st_gid
            ):
                raise
        os.chmod(database_staging, stat.S_IMODE(database_metadata.st_mode))
        with database_staging.open("rb") as staged_file:
            os.fsync(staged_file.fileno())

        if file_state == "present":
            assert files_backup_path is not None
            shutil.copytree(files_backup_path, stage_root, copy_function=shutil.copy2)
            payload = _manifest_inventory(file_manifest)  # type: ignore[arg-type]
            if not _verify_file_backup(payload, stage_root):
                raise RuntimeError("staged Graph file rollback failed verification")
            _restore_graph_file_metadata(stage_root, payload)

        # SQLite's WAL is a separate file and must not be replayed over the
        # restored snapshot. The app is offline at this point; checkpoint any
        # committed migration state and remove its sidecars before replacement.
        with sqlite3.connect(database, timeout=30) as current:
            checkpoint = current.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is not None and int(checkpoint[0]) != 0:
                raise RuntimeError("live SQLite database is still busy")

        if file_state is not None:
            if graph_root.exists():
                os.replace(graph_root, displaced_root)
                graph_tree_displaced = True
            if file_state == "present":
                os.replace(stage_root, graph_root)
                graph_tree_installed = True

        for suffix in ("-wal", "-shm"):
            Path(f"{database}{suffix}").unlink(missing_ok=True)
        os.replace(database_staging, database)
        database_replaced = True
        if graph_tree_displaced:
            try:
                if displaced_root.is_dir():
                    shutil.rmtree(displaced_root)
                else:
                    displaced_root.unlink(missing_ok=True)
            except OSError:
                # The restored database and file tree are already installed.
                # Keeping the displaced failed-release tree is safer than
                # rolling back a completed SQLite replacement.
                displaced_graph_files_retained = True
        return {
            "restored": True,
            "database_integrity": "ok",
            "graph_files_state": file_state or "not_restored",
            "graph_files_restored": file_state is not None,
            "displaced_graph_files_retained": displaced_graph_files_retained,
            "backup_fingerprint": expected_fingerprint["sha256"],
        }
    except Exception:
        if not database_replaced and graph_tree_installed and graph_root.exists():
            shutil.rmtree(graph_root)
        if not database_replaced and graph_tree_displaced and displaced_root.exists():
            os.replace(displaced_root, graph_root)
        raise
    finally:
        database_staging.unlink(missing_ok=True)
        if stage_root.exists():
            shutil.rmtree(stage_root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--graph-files", type=Path)
    parser.add_argument("--files-backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore-backup", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    if args.apply and args.restore_backup:
        parser.error("--apply and --restore-backup cannot be combined")
    if args.database is None or args.graph_files is None:
        import settings

        database = args.database or Path(settings.CACHE_DB_PATH)
        graph_files = args.graph_files or Path(settings.DATA_DIR) / "research-graphs"
    else:
        database = args.database
        graph_files = args.graph_files
    database = database.expanduser().resolve()
    graph_files = graph_files.expanduser()
    if not database.is_file():
        parser.error("database does not exist")
    if args.restore_backup:
        if args.backup is None:
            parser.error("--restore-backup requires --backup")
        result = restore_backup(
            database,
            args.backup,
            graph_files=graph_files,
            files_backup=args.files_backup,
        )
    elif args.apply:
        if args.backup is None:
            parser.error("--apply requires --backup")
        result = apply(
            database,
            args.backup,
            graph_files=graph_files,
            files_backup=args.files_backup,
        )
    else:
        with connect_sqlite(database, readonly=True) as conn:
            report = inspect(conn, graph_files=graph_files)
            result = {"dry_run": True, **report}
    if args.summary_only:
        if args.restore_backup:
            result = {
                "restored": result["restored"],
                "database_integrity": result["database_integrity"],
                "graph_files_state": result["graph_files_state"],
                "graph_files_restored": result["graph_files_restored"],
                "displaced_graph_files_retained": result[
                    "displaced_graph_files_retained"
                ],
            }
        elif args.apply:
            before = result["before"]
            after = result["after"]
            result = {
                "applied": True,
                "graph_tables_removed": len(before["graph_tables"]),
                "graph_evidence_admissions_removed": result[
                    "graph_evidence_admissions_removed"
                ],
                "maintenance_graph_refs_removed": result[
                    "maintenance_graph_refs_removed"
                ],
                "preserved_before": {
                    table: item["count"] for table, item in before["preserved"].items()
                },
                "preserved_after": {
                    table: item["count"] for table, item in after["preserved"].items()
                },
                "database_integrity": "ok",
            }
        else:
            result = _summary_report(result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _summary_report(report: dict[str, Any]) -> dict[str, Any]:
    work_required = bool(
        report["graph_tables"]
        or report["legacy_backend_receipts"]
        or report["graph_evidence_admissions"]
        or report["maintenance_graph_refs"]["refs"]
        or report["run_columns"]
        or report["report_evidence_graph_column"]
        or report["graph_files"]["state"] == "present"
    )
    return {
        "dry_run": True,
        "ready_to_apply": report["ready_to_apply"],
        "work_required": work_required,
        "graph_table_count": len(report["graph_tables"]),
        "graph_rows": sum(report["graph_tables"].values()),
        "legacy_backend_receipts": report["legacy_backend_receipts"],
        "graph_evidence_admissions": report["graph_evidence_admissions"],
        "maintenance_graph_refs": report["maintenance_graph_refs"],
        "unknown_graph_table_count": len(report["unknown_graph_tables"]),
        "unknown_graph_column_count": len(report["unknown_graph_columns"]),
        "external_graph_foreign_key_count": len(report["external_graph_foreign_keys"]),
        "run_columns": report["run_columns"],
        "run_retired_column_values": report["run_retired_column_values"],
        "report_evidence_graph_column": report["report_evidence_graph_column"],
        "report_evidence_graph_ref_values": report[
            "report_evidence_graph_ref_values"
        ],
        "graph_files": {
            "state": report["graph_files"]["state"],
            "file_count": report["graph_files"]["file_count"],
            "bytes": report["graph_files"]["bytes"],
        },
        "preserved_rows": {
            table: item["count"] for table, item in report["preserved"].items()
        },
        "blockers": report["blockers"],
    }


if __name__ == "__main__":
    main()

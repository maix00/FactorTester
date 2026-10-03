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
from pathlib import Path
import shutil
import sqlite3
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
        return {"state": "not_configured", "file_count": 0, "bytes": 0, "files": []}
    supplied = Path(path).expanduser()
    if supplied.name != "research-graphs":
        raise ValueError("--graph-files must point to the exact research-graphs directory")
    if supplied.is_symlink():
        raise ValueError("Graph files directory must not be a symbolic link")
    root = supplied.resolve(strict=False)
    if not root.exists():
        return {"state": "absent", "path": str(root), "file_count": 0, "bytes": 0, "files": []}
    if not root.is_dir():
        raise ValueError("Graph files path is not a directory")
    entries = []
    total_bytes = 0
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError("Graph files directory contains a symbolic link")
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
        })
    return {
        "state": "present",
        "path": str(root),
        "file_count": len(entries),
        "bytes": total_bytes,
        "files": entries,
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
    if inventory["state"] == "absent":
        return root, None
    if files_backup is None:
        raise ValueError("--files-backup is required when Graph files exist")
    backup = Path(files_backup).expanduser().resolve(strict=False)
    if backup.exists():
        raise FileExistsError(f"files backup already exists: {backup}")
    if backup == database or backup == database_backup:
        raise ValueError("file backup must be separate from the database and its backup")
    if backup == root or root in backup.parents or backup in root.parents:
        raise ValueError("file backup must be outside the Graph files directory")
    return root, backup


def _verify_file_backup(inventory: dict[str, Any], backup: Path) -> bool:
    expected = {
        item["path"]: (int(item["bytes"]), str(item["sha256"]))
        for item in inventory["files"]
    }
    actual: dict[str, tuple[int, str]] = {}
    if not backup.is_dir():
        return False
    for item in sorted(backup.rglob("*")):
        if item.is_symlink():
            return False
        if not item.is_file():
            continue
        digest = hashlib.sha256()
        size = 0
        with item.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        actual[item.relative_to(backup).as_posix()] = (size, digest.hexdigest())
    return actual == expected


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

    if files_backup_path is not None:
        files_backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(files_root, files_backup_path, copy_function=shutil.copy2)
        if not _verify_file_backup(preflight["graph_files"], files_backup_path):
            raise RuntimeError("Graph files backup verification failed")
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

            if files_backup_path is not None:
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
            conn.commit()
            return {
                "backup": str(backup),
                "files_backup": str(files_backup_path) if files_backup_path else None,
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
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--graph-files", type=Path, required=True)
    parser.add_argument("--files-backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    database = args.database.expanduser().resolve()
    if not database.is_file():
        parser.error("database does not exist")
    if args.apply:
        if args.backup is None:
            parser.error("--apply requires --backup")
        result = apply(
            database,
            args.backup,
            graph_files=args.graph_files,
            files_backup=args.files_backup,
        )
    else:
        with connect_sqlite(database, readonly=True) as conn:
            result = {
                "database": str(database),
                "dry_run": True,
                **inspect(conn, graph_files=args.graph_files),
            }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

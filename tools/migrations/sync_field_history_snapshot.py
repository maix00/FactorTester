"""Export and transactionally install the authoritative FieldHistory domain.

The snapshot deliberately contains only the append-only source events and their
runtime history projection.  Destination-local accounts, products, jobs, and
other SQLite domains are never copied or replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA_VERSION = 1
SOURCE_TABLES = ("agent_field_change_events", "historical_field_values")
MATERIALIZED_TABLES = (
    "field_history_unified",
    "field_history_transaction_fee_unified",
    "field_history_transaction_fee_exchange",
    "field_history_transaction_fee_broker_openctp",
    "field_history_transaction_fee_unit_classification",
    "field_history_transaction_fee_verification",
)
MANIFEST_TABLE = "field_history_snapshot_manifest"


def export_snapshot(source_path: Path, snapshot_path: Path) -> dict[str, Any]:
    if snapshot_path.exists():
        raise FileExistsError(snapshot_path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        _connect(source_path, readonly=True) as source,
        _connect(snapshot_path) as target,
    ):
        table_counts: dict[str, int] = {}
        target.execute("BEGIN IMMEDIATE")
        for table in SOURCE_TABLES:
            create_sql = _table_create_sql(source, table)
            target.execute(create_sql)
            columns = _table_columns(source, table)
            rows = source.execute(
                f'SELECT * FROM "{table}" ORDER BY {", ".join(_quote(column) for column in columns)}'
            ).fetchall()
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                target.executemany(
                    f'INSERT INTO "{table}" VALUES ({placeholders})',
                    [tuple(row) for row in rows],
                )
            table_counts[table] = len(rows)
        manifest = _manifest(target, table_counts=table_counts)
        target.execute(f"CREATE TABLE {MANIFEST_TABLE} (manifest_json TEXT NOT NULL)")
        target.execute(
            f"INSERT INTO {MANIFEST_TABLE} VALUES (?)",
            (json.dumps(manifest, ensure_ascii=False, sort_keys=True),),
        )
        target.commit()
    return manifest


def inspect_snapshot(snapshot_path: Path) -> dict[str, Any]:
    with _connect(snapshot_path, readonly=True) as snapshot:
        row = snapshot.execute(f"SELECT manifest_json FROM {MANIFEST_TABLE}").fetchone()
        if row is None:
            raise ValueError("FieldHistory snapshot has no manifest")
        stored = json.loads(str(row[0]))
        counts = {
            table: int(
                snapshot.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in SOURCE_TABLES
        }
        actual = _manifest(snapshot, table_counts=counts)
        if stored != actual:
            raise ValueError("FieldHistory snapshot manifest mismatch")
        return actual


def install_snapshot(
    snapshot_path: Path,
    destination_path: Path,
    backup_path: Path,
    *,
    apply: bool,
) -> dict[str, Any]:
    manifest = inspect_snapshot(snapshot_path)
    destination_path = destination_path.resolve()
    backup_path = backup_path.resolve()
    if destination_path == backup_path:
        raise ValueError("backup path must differ from destination path")
    if not apply:
        return manifest
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise FileExistsError(backup_path)
    with _connect(destination_path) as destination, _connect(backup_path) as backup:
        destination.backup(backup)
    if _integrity_check(backup_path) != "ok":
        raise RuntimeError("FieldHistory destination backup failed integrity check")
    try:
        _replace_source_tables(snapshot_path, destination_path)
        _materialize(destination_path)
        if _integrity_check(destination_path) != "ok":
            raise RuntimeError("FieldHistory destination failed integrity check")
        _verify_installed(destination_path, manifest)
    except BaseException:
        _restore_backup(backup_path, destination_path)
        raise
    return manifest


def _replace_source_tables(snapshot_path: Path, destination_path: Path) -> None:
    with (
        _connect(snapshot_path, readonly=True) as snapshot,
        _connect(destination_path) as destination,
    ):
        destination.execute("PRAGMA foreign_keys = OFF")
        destination.execute("BEGIN IMMEDIATE")
        for table in (*MATERIALIZED_TABLES, *SOURCE_TABLES):
            destination.execute(f'DROP TABLE IF EXISTS "{table}"')
        for table in SOURCE_TABLES:
            destination.execute(_table_create_sql(snapshot, table))
            columns = _table_columns(snapshot, table)
            rows = snapshot.execute(f'SELECT * FROM "{table}"').fetchall()
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                destination.executemany(
                    f'INSERT INTO "{table}" VALUES ({placeholders})',
                    [tuple(row) for row in rows],
                )
        destination.commit()


def _materialize(destination_path: Path) -> None:
    import settings as Settings
    from sources.FieldHistory.views.TransactionFee import (
        save_unified_table as save_fee_tables,
    )
    from sources.FieldHistory.views.Unified import save_unified_table
    from tools.data.field_history import _ensure_schema
    from tools.data.field_history_agent_ingest import ensure_agent_event_schema

    expected = Path(Settings.CACHE_DB_PATH).resolve()
    if destination_path.resolve() != expected:
        raise ValueError("destination is not the configured unified SQLite database")
    with _connect(destination_path) as connection:
        _ensure_schema(connection)
        ensure_agent_event_schema(connection)
    save_unified_table(store_key="openctp")
    save_fee_tables(store_key="openctp")


def _verify_installed(destination_path: Path, manifest: dict[str, Any]) -> None:
    with _connect(destination_path, readonly=True) as destination:
        for table, expected in manifest["table_counts"].items():
            actual = int(
                destination.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            if actual != int(expected):
                raise RuntimeError(
                    f"FieldHistory row-count mismatch for {table}: {actual} != {expected}"
                )
        for table in MATERIALIZED_TABLES[:4]:
            exists = destination.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists is None:
                raise RuntimeError(f"FieldHistory materialized table missing: {table}")


def _restore_backup(backup_path: Path, destination_path: Path) -> None:
    with (
        _connect(backup_path, readonly=True) as backup,
        _connect(destination_path) as destination,
    ):
        backup.backup(destination)


def _manifest(
    connection: sqlite3.Connection, *, table_counts: dict[str, int]
) -> dict[str, Any]:
    digest = hashlib.sha256()
    for table in SOURCE_TABLES:
        columns = _table_columns(connection, table)
        digest.update(table.encode())
        digest.update(json.dumps(columns, separators=(",", ":")).encode())
        query = f'SELECT * FROM "{table}" ORDER BY {", ".join(_quote(column) for column in columns)}'
        for row in connection.execute(query):
            digest.update(
                json.dumps(
                    list(row), ensure_ascii=False, separators=(",", ":"), default=str
                ).encode()
            )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "tables": list(SOURCE_TABLES),
        "table_counts": table_counts,
        "content_sha256": digest.hexdigest(),
    }


def _table_create_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if row is None or not row[0]:
        raise ValueError(f"required FieldHistory table is missing: {table}")
    return str(row[0])


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    columns = [
        str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
    ]
    if not columns:
        raise ValueError(f"required FieldHistory table has no columns: {table}")
    return columns


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _integrity_check(path: Path) -> str:
    with _connect(path, readonly=True) as connection:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("source", type=Path)
    export_parser.add_argument("snapshot", type=Path)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("snapshot", type=Path)
    install_parser.add_argument("destination", type=Path)
    install_parser.add_argument("backup", type=Path)
    install_parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.command == "export":
        manifest = export_snapshot(args.source, args.snapshot)
    else:
        manifest = install_snapshot(
            args.snapshot, args.destination, args.backup, apply=args.apply
        )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Rebuildable SQLite indexes for one branch report tree."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from tools.cli.core.sqlite import connect_sqlite

from .tree_schema import identifier
from .tree_store import atomic_write, load_node

SCHEMA_VERSION = 1


def ensure_sqlite_index(
    paths: dict[str, Path], root: dict[str, Any], generation: int,
) -> None:
    if index_generation(paths) == generation:
        return
    historical = _registered_binding_ids(paths)
    current_bindings: set[str] = set()
    locators: list[tuple[str, str]] = []
    _collect_tree(paths, root, None, locators, current_bindings)
    historical.update(current_bindings)
    _write_binding_registry(paths, historical)
    _rebuild(paths, generation, locators, historical)


def index_generation(paths: dict[str, Path]) -> int | None:
    path = paths["index_db"]
    if not path.is_file():
        return None
    try:
        with _connect(path, readonly=True) as db:
            row = db.execute(
                "SELECT value FROM metadata WHERE key = 'generation'"
            ).fetchone()
            schema = db.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
    except (OSError, sqlite3.DatabaseError):
        return None
    if not row or not schema or int(schema[0]) != SCHEMA_VERSION:
        return None
    return int(row[0])


def component_parent(
    paths: dict[str, Path], node_id: str, visible_generation: int,
) -> str | None:
    identifier(node_id, "node_id")
    if index_generation(paths) is None:
        return None
    try:
        with _connect(paths["index_db"], readonly=True) as db:
            row = db.execute(
                "SELECT parent_id, generation FROM component_locator "
                "WHERE node_id = ?", (node_id,),
            ).fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None or int(row[1]) > visible_generation:
        return None
    return str(row[0])


def component_exists(
    paths: dict[str, Path], node_id: str, visible_generation: int,
) -> bool:
    return component_parent(paths, node_id, visible_generation) is not None


def binding_exists(
    paths: dict[str, Path], binding_id: str, visible_generation: int,
) -> bool:
    identifier(binding_id, "binding.binding_id")
    if index_generation(paths) is None:
        return False
    try:
        with _connect(paths["index_db"], readonly=True) as db:
            row = db.execute(
                "SELECT generation FROM binding_registry WHERE binding_id = ?",
                (binding_id,),
            ).fetchone()
    except sqlite3.DatabaseError:
        return False
    return row is not None and int(row[0]) <= visible_generation


def publish_sqlite_index(
    paths: dict[str, Path], root: dict[str, Any], generation: int,
) -> None:
    registered = _registered_binding_ids(paths)
    current_bindings: set[str] = set()
    locators: list[tuple[str, str]] = []
    _collect_tree(paths, root, None, locators, current_bindings)
    registered.update(current_bindings)
    _write_binding_registry(paths, registered)
    _rebuild(paths, generation, locators, registered)


def verify_sqlite_index(
    paths: dict[str, Path], root: dict[str, Any], generation: int,
) -> dict[str, int]:
    expected_locators: list[tuple[str, str]] = []
    expected_bindings: set[str] = set()
    _collect_tree(paths, root, None, expected_locators, expected_bindings)
    if index_generation(paths) != generation:
        raise ValueError("report SQLite index generation does not match HEAD")
    with _connect(paths["index_db"], readonly=True) as db:
        actual_locators = {
            (str(row[0]), str(row[1])) for row in db.execute(
                "SELECT node_id,parent_id FROM component_locator"
            )
        }
        actual_bindings = {
            str(row[0]) for row in db.execute(
                "SELECT binding_id FROM binding_registry"
            )
        }
    if actual_locators != set(expected_locators):
        raise ValueError("report SQLite component index does not match tree")
    if not expected_bindings.issubset(actual_bindings):
        raise ValueError("report SQLite binding index does not match tree")
    return {
        "components": len(actual_locators),
        "current_bindings": len(expected_bindings),
        "registered_bindings": len(actual_bindings),
    }


def _rebuild(
    paths: dict[str, Path], generation: int,
    locators: list[tuple[str, str]], bindings: set[str],
) -> None:
    path = paths["index_db"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.unlink(missing_ok=True)
    with _connect(temp) as db:
        _create_schema(db)
        db.executemany(
            "INSERT INTO component_locator(node_id,parent_id,generation) "
            "VALUES(?,?,?)",
            ((node, parent, generation) for node, parent in locators),
        )
        db.executemany(
            "INSERT INTO binding_registry(binding_id,generation) VALUES(?,?)",
            ((binding_id, generation) for binding_id in sorted(bindings)),
        )
        db.execute(
            "INSERT INTO metadata(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        db.execute(
            "INSERT INTO metadata(key,value) VALUES('generation',?)",
            (str(generation),),
        )
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("report SQLite index integrity check failed")
    temp.replace(path)


def _create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE metadata(
            key TEXT PRIMARY KEY NOT NULL,
            value TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE component_locator(
            node_id TEXT PRIMARY KEY NOT NULL,
            parent_id TEXT NOT NULL,
            generation INTEGER NOT NULL
        ) WITHOUT ROWID;
        CREATE INDEX component_locator_parent
            ON component_locator(parent_id);
        CREATE TABLE binding_registry(
            binding_id TEXT PRIMARY KEY NOT NULL,
            generation INTEGER NOT NULL
        ) WITHOUT ROWID;
    """)


def _collect_tree(
    paths: dict[str, Path], node: dict[str, Any], parent_id: str | None,
    locators: list[tuple[str, str]], bindings: set[str],
) -> None:
    node_id = str(node["node_id"])
    if node_id != "root":
        locators.append((node_id, parent_id or "root"))
    for binding in node["bindings"]:
        bindings.add(str(binding["binding_id"]))
    for child in node["children"]:
        _collect_tree(
            paths, load_node(paths, child["ref"]),
            None if node_id == "root" else node_id,
            locators, bindings,
        )


def _registered_binding_ids(paths: dict[str, Path]) -> set[str]:
    registry = paths["binding_registry"]
    result: set[str] = set()
    if registry.is_file():
        for line in registry.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            result.add(identifier(value["binding_id"], "binding.binding_id"))
    return result


def _write_binding_registry(
    paths: dict[str, Path], binding_ids: set[str],
) -> None:
    payload = b"".join(
        json.dumps(
            {"binding_id": binding_id}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        for binding_id in sorted(binding_ids)
    )
    atomic_write(paths["binding_registry"], payload)


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    connection = connect_sqlite(path, readonly=readonly)
    if readonly:
        return connection
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    return connection

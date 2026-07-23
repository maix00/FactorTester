"""Private, one-shot recovery of exact canonical Graph v1-v3 history."""

from __future__ import annotations

from dataclasses import dataclass
import base64
from collections.abc import Callable
import gzip
import hashlib
from pathlib import Path
import sqlite3
import time
from typing import Any

import orjson

from server.services.research_graph.history_artifacts import (
    compressed_history_artifacts,
)
from server.services.research_graph.protocol import (
    graph_content_hash,
    validate_graph,
)
from server.services.research_graph.versions import (
    clear_graph_cache_for_current_db,
)
from tools.data.sqlite.db import connect_sqlite


_GRAPH_ID = "factor-research"
_HISTORY_VERSIONS = (1, 2, 3)
_PRESERVED_VERSIONS = tuple(range(4, 10))
_EXPECTED_HISTORY = {
    1: {
        "content_hash": (
            "d8d76b80fbca0342d3b8477e1594bfd7"
            "da1dab2924c7d2d078bf64e8ba44d64e"
        ),
        "bytes": 6974,
        "lifecycle": "observed",
        "parent_version": 0,
        "nodes": 13,
        "edges": 13,
    },
    2: {
        "content_hash": (
            "95a82ea250f1502b7ce7706f85a66373"
            "8afc08f5ec7f8bcebc71d7082f6bf689"
        ),
        "bytes": 22130,
        "lifecycle": "draft",
        "parent_version": 1,
        "nodes": 14,
        "edges": 19,
    },
    3: {
        "content_hash": (
            "ae7bbc1ad50b22e75c6f781ced3510cd"
            "05de250f966bbb402e7bba999421c3b2"
        ),
        "bytes": 24696,
        "lifecycle": "draft",
        "parent_version": 2,
        "nodes": 14,
        "edges": 21,
    },
}
_PRESERVED_TABLES = (
    "active_research_graphs",
    "research_graph_instances",
    "research_graph_branches",
    "research_graph_trace",
    "research_runs",
    "research_jobs",
)


@dataclass(frozen=True)
class HistoryArtifact:
    version: int
    source_commit: str
    graph_json: bytes
    graph: dict[str, Any]

    @property
    def content_hash(self) -> str:
        return str(self.graph["content_hash"])

    @property
    def lifecycle(self) -> str:
        return str(self.graph["lifecycle"])

    @property
    def parent_version(self) -> int:
        return int(self.graph.get("parent_version") or 0)


def canonical_history_artifacts() -> tuple[HistoryArtifact, ...]:
    artifacts = []
    for version, (source_commit, encoded) in sorted(
        compressed_history_artifacts().items()
    ):
        graph_json = gzip.decompress(base64.b64decode(encoded))
        graph = orjson.loads(graph_json)
        validated = validate_graph(graph)
        if int(validated["version"]) != version:
            raise ValueError("history artifact version does not match")
        if graph_content_hash(validated) != validated["content_hash"]:
            raise ValueError("history artifact content hash does not match")
        canonical = orjson.dumps(validated, option=orjson.OPT_SORT_KEYS)
        if canonical != graph_json:
            raise ValueError("history artifact bytes are not canonical")
        identity = {
            "content_hash": str(validated["content_hash"]),
            "bytes": len(graph_json),
            "lifecycle": str(validated["lifecycle"]),
            "parent_version": int(validated.get("parent_version") or 0),
            "nodes": len(validated["nodes"]),
            "edges": len(validated["edges"]),
        }
        if identity != _EXPECTED_HISTORY[version]:
            raise ValueError(
                f"Graph v{version} does not match audited history identity"
            )
        artifacts.append(HistoryArtifact(
            version=version,
            source_commit=source_commit,
            graph_json=graph_json,
            graph=validated,
        ))
    if tuple(item.version for item in artifacts) != _HISTORY_VERSIONS:
        raise ValueError("canonical Graph history is incomplete")
    return tuple(artifacts)


def inspect_history_recovery(*, db_path: str | Path) -> dict[str, Any]:
    artifacts = canonical_history_artifacts()
    with connect_sqlite(Path(db_path)) as conn:
        _require_integrity(conn)
        before = _preserved_snapshot(conn)
        state = _history_state(conn, artifacts)
    return _plan(artifacts=artifacts, before=before, state=state)


def recover_history(
    *,
    db_path: str | Path,
    backup_path: str | Path,
    expected_plan_hash: str = "",
    failure_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if not expected_plan_hash:
        raise ValueError(
            "expected_plan_hash is required for history recovery"
        )
    database = Path(db_path).expanduser().resolve()
    backup = Path(backup_path).expanduser().resolve()
    plan = inspect_history_recovery(db_path=database)
    if expected_plan_hash and plan["plan_hash"] != expected_plan_hash:
        raise ValueError("history recovery plan hash changed")
    if plan["status"] == "already_recovered":
        return {**plan, "applied": False, "backup_path": ""}
    if plan["status"] != "ready":
        raise ValueError(str(plan["blocking_reason"]))
    _backup_database(database, backup)

    artifacts = canonical_history_artifacts()
    with connect_sqlite(database) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _require_integrity(conn)
            current_before = _preserved_snapshot(conn)
            current_state = _history_state(conn, artifacts)
            current_plan = _plan(
                artifacts=artifacts,
                before=current_before,
                state=current_state,
            )
            if current_plan["plan_hash"] != plan["plan_hash"]:
                raise ValueError("database changed after recovery planning")
            created_at = time.time()
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO research_graph_versions (
                        graph_id, version, lifecycle, parent_version,
                        content_hash, graph_json, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _GRAPH_ID,
                        artifact.version,
                        artifact.lifecycle,
                        artifact.parent_version,
                        artifact.content_hash,
                        artifact.graph_json.decode(),
                        f"history-recovery:{artifact.source_commit}",
                        created_at,
                    ),
                )
                if failure_injector is not None:
                    failure_injector(f"after_v{artifact.version}")
            _require_lineage(conn, artifacts)
            if _preserved_snapshot(conn) != current_before:
                raise RuntimeError("preserved database state changed")
            conn.commit()
        except Exception:
            conn.rollback()
            clear_graph_cache_for_current_db()
            raise
    clear_graph_cache_for_current_db()
    after = inspect_history_recovery(db_path=database)
    if after["status"] != "already_recovered":
        raise RuntimeError("history recovery postcondition failed")
    if after["preserved_snapshot"] != plan["preserved_snapshot"]:
        raise RuntimeError("preserved database state changed after commit")
    return {
        **after,
        "applied": True,
        "inserted_versions": list(_HISTORY_VERSIONS),
        "backup_path": str(backup),
    }


def _plan(
    *,
    artifacts: tuple[HistoryArtifact, ...],
    before: dict[str, Any],
    state: str,
) -> dict[str, Any]:
    blocking_reason = ""
    if state == "partial":
        blocking_reason = "Graph v1-v3 recovery is partial"
    elif state == "mismatch":
        blocking_reason = "Graph v1-v3 conflicts with canonical history"
    status = {
        "missing": "ready",
        "exact": "already_recovered",
    }.get(state, "blocked")
    identity = {
        "graph_id": _GRAPH_ID,
        "artifacts": [
            {
                "version": item.version,
                "content_hash": item.content_hash,
                "bytes": len(item.graph_json),
                "source_commit": item.source_commit,
            }
            for item in artifacts
        ],
        "preserved_snapshot": before,
        "state": state,
    }
    return {
        **identity,
        "status": status,
        "blocking_reason": blocking_reason,
        "plan_hash": _json_hash(identity),
    }


def _history_state(
    conn: sqlite3.Connection,
    artifacts: tuple[HistoryArtifact, ...],
) -> str:
    rows = conn.execute(
        """
        SELECT version, lifecycle, parent_version, content_hash, graph_json
        FROM research_graph_versions
        WHERE graph_id=? AND version BETWEEN 1 AND 3
        ORDER BY version
        """,
        (_GRAPH_ID,),
    ).fetchall()
    if not rows:
        return "missing"
    if len(rows) != len(artifacts):
        return "partial"
    for row, artifact in zip(rows, artifacts, strict=True):
        if (
            int(row["version"]) != artifact.version
            or str(row["lifecycle"]) != artifact.lifecycle
            or int(row["parent_version"]) != artifact.parent_version
            or str(row["content_hash"]) != artifact.content_hash
            or str(row["graph_json"]).encode() != artifact.graph_json
        ):
            return "mismatch"
    return "exact"


def _preserved_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    versions = conn.execute(
        """
        SELECT graph_id, version, lifecycle, parent_version, content_hash,
               graph_json, created_by, created_at
        FROM research_graph_versions
        WHERE graph_id=? AND version BETWEEN 4 AND 9
        ORDER BY version
        """,
        (_GRAPH_ID,),
    ).fetchall()
    if tuple(int(row["version"]) for row in versions) != _PRESERVED_VERSIONS:
        raise ValueError("Graph v4-v9 must exist before history recovery")
    if int(versions[0]["parent_version"]) != 3:
        raise ValueError("Graph v4 must retain parent_version=3")
    result = {
        "graph_v4_v9": _rows_digest(versions),
        "graph_v4_v9_raw_bytes": [
            len(str(row["graph_json"]).encode()) for row in versions
        ],
    }
    for table in _PRESERVED_TABLES:
        result[table] = _table_digest(conn, table)
    return result


def _require_lineage(
    conn: sqlite3.Connection,
    artifacts: tuple[HistoryArtifact, ...],
) -> None:
    rows = conn.execute(
        """
        SELECT version, parent_version FROM research_graph_versions
        WHERE graph_id=? AND version BETWEEN 1 AND 4 ORDER BY version
        """,
        (_GRAPH_ID,),
    ).fetchall()
    if [
        (int(row["version"]), int(row["parent_version"]))
        for row in rows
    ] != [(1, 0), (2, 1), (3, 2), (4, 3)]:
        raise RuntimeError("recovered Graph lineage is not continuous")
    if _history_state(conn, artifacts) != "exact":
        raise RuntimeError("recovered Graph history is not canonical")


def _table_digest(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    exists = conn.execute(
        """
        SELECT 1 FROM sqlite_master WHERE type='table' AND name=?
        """,
        (table,),
    ).fetchone()
    if exists is None:
        raise ValueError(f"required preserved table is missing: {table}")
    columns = [
        str(row["name"])
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    ]
    rows = conn.execute(
        f'SELECT * FROM "{table}" ORDER BY rowid'
    ).fetchall()
    return {"count": len(rows), "digest": _rows_digest(rows, columns=columns)}


def _rows_digest(
    rows: list[Any],
    *,
    columns: list[str] | None = None,
) -> str:
    values = []
    for row in rows:
        names = columns or list(row.keys())
        values.append({
            name: _json_value(row[name])
            for name in names
        })
    return hashlib.sha256(
        orjson.dumps(values, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode()}
    return value


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _require_integrity(conn: sqlite3.Connection) -> None:
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if result is None or str(result[0]).lower() != "ok":
        raise RuntimeError("SQLite integrity_check failed")


def _backup_database(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"backup already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_conn:
        with sqlite3.connect(target) as target_conn:
            source_conn.backup(target_conn)
    with sqlite3.connect(target) as backup_conn:
        result = backup_conn.execute("PRAGMA integrity_check").fetchone()
    if result is None or str(result[0]).lower() != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError("SQLite backup integrity_check failed")

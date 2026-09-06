"""Manager-local SQLite mirror and durable outbox for account metadata."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Iterable

from tools.data.sqlite.db import connect_sqlite


ENTITY_TYPES = {
    "user_metadata",
    "organization",
    "level",
    "profile",
    "factor_set",
    "factor_param_config",
    "factor_source",
    "factor_family",
    "factor_research_run",
    "product_category",
    "product_group",
    "research_publication",
    "strategy",
    "strategy_revision",
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the mirror tables in the existing Manager SQLite database."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS account_domain_entities (
            principal TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0,
            remote_revision INTEGER,
            base_revision INTEGER,
            origin_manager_id TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            PRIMARY KEY (principal, entity_type, entity_id)
        );
        CREATE INDEX IF NOT EXISTS account_domain_entities_type
            ON account_domain_entities(entity_type, principal, updated_at DESC);
        CREATE INDEX IF NOT EXISTS account_domain_entities_remote_revision
            ON account_domain_entities(remote_revision);

        CREATE INDEX IF NOT EXISTS account_domain_factor_catalog_config
            ON account_domain_entities(principal, json_extract(payload_json, '$.source_config_id'))
            WHERE entity_type='factor_catalog_entry';

        CREATE INDEX IF NOT EXISTS account_domain_factor_catalog_ref
            ON account_domain_entities(principal, json_extract(payload_json, '$.factor.factor_ref'))
            WHERE entity_type='factor_catalog_entry';

        CREATE TABLE IF NOT EXISTS account_domain_outbox (
            operation_id TEXT PRIMARY KEY,
            principal TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0,
            base_revision INTEGER,
            created_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS account_domain_outbox_entity
            ON account_domain_outbox(principal, entity_type, entity_id, created_at);

        CREATE TABLE IF NOT EXISTS account_domain_cursors (
            scope_key TEXT PRIMARY KEY,
            remote_revision INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS account_domain_conflicts (
            conflict_id TEXT PRIMARY KEY,
            principal TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            local_payload_json TEXT NOT NULL,
            remote_payload_json TEXT NOT NULL,
            remote_deleted INTEGER NOT NULL DEFAULT 0,
            remote_revision INTEGER,
            status TEXT NOT NULL DEFAULT 'open',
            created_at REAL NOT NULL,
            resolved_at REAL
        );
        CREATE INDEX IF NOT EXISTS account_domain_conflicts_entity
            ON account_domain_conflicts(principal, entity_type, entity_id, status);
        """
    )


class LocalAccountDomainStore:
    """Small SQLite repository; it never opens PostgreSQL."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connect_sqlite(self.path) as conn:
            ensure_schema(conn)

    def upsert_local(
        self,
        *,
        principal: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        manager_id: str,
        deleted: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        now = time.time()
        operation_id = uuid.uuid4().hex
        encoded = _encode(payload)
        with (nullcontext(connection) if connection is not None else connect_sqlite(self.path)) as conn:
            if connection is None:
                conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """
                SELECT remote_revision, payload_json, deleted FROM account_domain_entities
                WHERE principal=? AND entity_type=? AND entity_id=?
                """,
                (principal, entity_type, entity_id),
            ).fetchone()
            previous = conn.execute(
                "SELECT operation_id, last_error FROM account_domain_outbox "
                "WHERE principal=? AND entity_type=? AND entity_id=?",
                (principal, entity_type, entity_id),
            ).fetchone()
            if current and current["payload_json"] == encoded and bool(current["deleted"]) == bool(deleted):
                return str(previous["operation_id"]) if previous else ""
            blocked = bool(previous and previous["last_error"] == "remote revision conflict")
            base_revision = (
                int(current["remote_revision"])
                if current and current["remote_revision"] is not None else None
            )
            conn.execute(
                """
                INSERT INTO account_domain_entities(
                    principal, entity_type, entity_id, payload_json, deleted,
                    remote_revision, base_revision, origin_manager_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
                ON CONFLICT(principal, entity_type, entity_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    deleted=excluded.deleted,
                    base_revision=excluded.base_revision,
                    origin_manager_id=excluded.origin_manager_id,
                    updated_at=excluded.updated_at
                """,
                (
                    principal, entity_type, entity_id, encoded, int(deleted),
                    base_revision, manager_id, now,
                ),
            )
            _materialize_factor_entries(conn, principal, entity_type, entity_id, payload, deleted, manager_id)
            # Coalesce local edits. The newest state is the only state that
            # needs to reach the authority; operation_id still makes retries
            # auditable and independent of a process lifetime.
            conn.execute(
                """
                DELETE FROM account_domain_outbox
                WHERE principal=? AND entity_type=? AND entity_id=?
                """,
                (principal, entity_type, entity_id),
            )
            conn.execute(
                """
                INSERT INTO account_domain_outbox(
                    operation_id, principal, entity_type, entity_id,
                    payload_json, deleted, base_revision, created_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, principal, entity_type, entity_id, encoded,
                    int(deleted), base_revision, now,
                    "remote revision conflict" if blocked else (
                        "factor materialization required" if entity_type == "factor_param_config"
                        and not deleted and not isinstance(payload.get("resolved_factors"), list) else ""
                    ),
                ),
            )
        return operation_id

    def pending(self, *, principal: str = "", limit: int = 100, include_blocked: bool = False) -> list[dict[str, Any]]:
        clauses = [] if include_blocked else ["last_error NOT IN ('remote revision conflict', 'factor materialization required')"]
        params: list[Any] = []
        if principal:
            clauses.append("principal=?")
            params.append(principal)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 1000)))
        with connect_sqlite(self.path) as conn:
            rows = conn.execute(
                f"""
                SELECT operation_id, principal, entity_type, entity_id,
                       payload_json, deleted, base_revision, attempts, last_error
                FROM account_domain_outbox{where}
                ORDER BY created_at, operation_id LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [_outbox_row(row) for row in rows]

    def discard_local_entity(
        self, principal: str, entity_type: str, entity_id: str,
    ) -> None:
        """Remove one superseded local identity and resolve its old conflicts."""
        with connect_sqlite(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            key = (principal, entity_type, entity_id)
            _materialize_factor_entries(conn, *key, {}, True, "")
            conn.execute(
                """
                DELETE FROM account_domain_outbox
                WHERE principal=? AND entity_type=? AND entity_id=?
                """,
                key,
            )
            conn.execute(
                """
                DELETE FROM account_domain_entities
                WHERE principal=? AND entity_type=? AND entity_id=?
                """,
                key,
            )
            conn.execute(
                """
                UPDATE account_domain_conflicts
                SET status='resolved', resolved_at=?
                WHERE principal=? AND entity_type=? AND entity_id=?
                  AND status='open'
                """,
                (time.time(), *key),
            )

    def mark_attempt(self, operation_id: str, error: str = "") -> None:
        with connect_sqlite(self.path) as conn:
            conn.execute(
                """
                UPDATE account_domain_outbox
                SET attempts=attempts+1, last_error=?
                WHERE operation_id=?
                """,
                (str(error or "")[:1000], operation_id),
            )

    def record_push_conflict(
        self, item: dict[str, Any], remote: dict[str, Any],
    ) -> None:
        """Persist a compare-and-set rejection for later user resolution."""
        with connect_sqlite(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            _record_conflict(conn, item, remote)
            conn.execute(
                "UPDATE account_domain_outbox SET last_error='remote revision conflict' WHERE operation_id=?",
                (item["operation_id"],),
            )

    def sync_state(self, *, principal: str = "") -> dict[str, int]:
        where = " WHERE principal=?" if principal else ""
        args = (principal,) if principal else ()
        with connect_sqlite(self.path) as conn:
            row = conn.execute(
                "SELECT count(*) AS pending, coalesce(sum(last_error='remote revision conflict'),0) AS blocked "
                "FROM account_domain_outbox" + where, args,
            ).fetchone()
        return {"pending": int(row["pending"]), "blocked": int(row["blocked"])}

    def resolve_conflict(
        self, *, principal: str, entity_type: str, entity_id: str,
        expected_payload: dict[str, Any], remote_revision: int,
        payload: dict[str, Any], manager_id: str, deleted: bool = False,
    ) -> str:
        """Queue an explicitly reviewed resolution against the observed authority.

        The local value and latest conflict revision are preconditions. A new
        authority edit is still protected by the normal remote compare-and-set.
        """
        key = (principal, entity_type, entity_id)
        encoded = _encode(payload)
        operation = uuid.uuid4().hex
        now = time.time()
        with connect_sqlite(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload_json FROM account_domain_entities WHERE principal=? AND entity_type=? AND entity_id=?", key,
            ).fetchone()
            latest = conn.execute(
                "SELECT max(remote_revision) FROM account_domain_conflicts "
                "WHERE principal=? AND entity_type=? AND entity_id=? AND status='open'", key,
            ).fetchone()[0]
            if row is None or row["payload_json"] != _encode(expected_payload) or latest != remote_revision:
                raise ValueError("conflict resolution precondition changed; inspect again")
            conn.execute(
                "UPDATE account_domain_entities SET payload_json=?, deleted=?, remote_revision=?, base_revision=?, "
                "origin_manager_id=?, updated_at=? WHERE principal=? AND entity_type=? AND entity_id=?",
                (encoded, int(deleted), remote_revision, remote_revision, manager_id, now, *key),
            )
            _materialize_factor_entries(conn, principal, entity_type, entity_id, payload, deleted, manager_id)
            conn.execute("DELETE FROM account_domain_outbox WHERE principal=? AND entity_type=? AND entity_id=?", key)
            conn.execute(
                "INSERT INTO account_domain_outbox(operation_id, principal, entity_type, entity_id, payload_json, "
                "deleted, base_revision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (operation, *key, encoded, int(deleted), remote_revision, now),
            )
            conn.execute(
                "UPDATE account_domain_conflicts SET status='resolved', resolved_at=? "
                "WHERE principal=? AND entity_type=? AND entity_id=? AND status='open'", (now, *key),
            )
        return operation

    def acknowledge(self, operation_id: str, *, revision: int, sent_item: dict[str, Any] | None = None) -> None:
        with connect_sqlite(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT principal, entity_type, entity_id
                FROM account_domain_outbox WHERE operation_id=?
                """,
                (operation_id,),
            ).fetchone()
            if row is None:
                if sent_item is None:
                    return
                # An edit coalesced the in-flight operation. Keep its payload,
                # but carry the successful CAS revision to its successor.
                key = (sent_item["principal"], sent_item["entity_type"], sent_item["entity_id"])
                changed = conn.execute(
                    "UPDATE account_domain_outbox SET base_revision=? WHERE principal=? AND entity_type=? AND entity_id=? "
                    "AND base_revision IS ? AND last_error != 'remote revision conflict'",
                    (revision, *key, sent_item["base_revision"]),
                ).rowcount
                if changed:
                    conn.execute(
                        "UPDATE account_domain_entities SET remote_revision=?, base_revision=? "
                        "WHERE principal=? AND entity_type=? AND entity_id=?", (revision, revision, *key),
                    )
                return
            conn.execute(
                """
                UPDATE account_domain_entities
                SET remote_revision=?, base_revision=?, updated_at=?
                WHERE principal=? AND entity_type=? AND entity_id=?
                """,
                (
                    int(revision), int(revision), time.time(),
                    row["principal"], row["entity_type"], row["entity_id"],
                ),
            )
            conn.execute(
                "DELETE FROM account_domain_outbox WHERE operation_id=?",
                (operation_id,),
            )

    def apply_remote(self, row: dict[str, Any]) -> str:
        principal = str(row.get("principal") or "").strip()
        entity_type = str(row.get("entity_type") or "").strip()
        entity_id = str(row.get("entity_id") or "").strip()
        payload = row.get("payload")
        if not principal or not entity_type or not entity_id or not isinstance(payload, dict):
            raise ValueError("remote account-domain row is invalid")
        revision = int(row.get("revision") or 0)
        deleted = bool(row.get("deleted"))
        with connect_sqlite(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute(
                """
                SELECT operation_id, payload_json, deleted FROM account_domain_outbox
                WHERE principal=? AND entity_type=? AND entity_id=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (principal, entity_type, entity_id),
            ).fetchone()
            if pending is not None:
                local = {
                    "payload": _decode(pending["payload_json"]),
                    "deleted": bool(pending["deleted"]),
                }
                if local != {"payload": payload, "deleted": deleted}:
                    _record_conflict(conn, {
                        "principal": principal, "entity_type": entity_type,
                        "entity_id": entity_id, "payload": local["payload"],
                    }, row)
                    conn.execute(
                        "UPDATE account_domain_outbox SET last_error='remote revision conflict' WHERE operation_id=?",
                        (pending["operation_id"],),
                    )
                    return "conflict"
            if pending is not None:
                conn.execute("DELETE FROM account_domain_outbox WHERE operation_id=?", (pending["operation_id"],))
            current = conn.execute(
                """
                SELECT remote_revision FROM account_domain_entities
                WHERE principal=? AND entity_type=? AND entity_id=?
                """,
                (principal, entity_type, entity_id),
            ).fetchone()
            if current and current["remote_revision"] is not None and int(current["remote_revision"]) >= revision:
                return "stale"
            conn.execute(
                """
                INSERT INTO account_domain_entities(
                    principal, entity_type, entity_id, payload_json, deleted,
                    remote_revision, base_revision, origin_manager_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(principal, entity_type, entity_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    deleted=excluded.deleted,
                    remote_revision=excluded.remote_revision,
                    base_revision=excluded.base_revision,
                    origin_manager_id=excluded.origin_manager_id,
                    updated_at=excluded.updated_at
                """,
                (
                    principal, entity_type, entity_id, _encode(payload),
                    int(deleted), revision, revision,
                    str(row.get("origin_manager_id") or ""), time.time(),
                ),
            )
            _materialize_factor_entries(conn, principal, entity_type, entity_id, payload, deleted, str(row.get("origin_manager_id") or ""))
        return "applied"

    def rebuild_factor_catalog(self, principal: str = "") -> int:
        """Explicit deployment backfill; normal reads never run migration work."""
        with connect_sqlite(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM account_domain_entities WHERE entity_type='factor_param_config'" +
                (" AND principal=?" if principal else ""), (principal,) if principal else (),
            ).fetchall()
            for row in rows:
                _materialize_factor_entries(conn, row["principal"], row["entity_type"], row["entity_id"],
                    _decode(row["payload_json"]), bool(row["deleted"]), row["origin_manager_id"])
        return len(rows)

    def factor_catalog(self, principal: str, *, factor_ref: str = "", offset: int = 0, limit: int | None = None) -> list[dict[str, Any]]:
        clauses = ["principal=?", "entity_type='factor_catalog_entry'", "deleted=0"]
        args: list[Any] = [principal]
        if factor_ref:
            clauses.append("json_extract(payload_json, '$.factor.factor_ref')=?")
            args.append(factor_ref)
        paging = ""
        if limit is not None:
            paging = " LIMIT ? OFFSET ?"
            args.extend((max(1, min(1000, int(limit))), max(0, int(offset))))
        with connect_sqlite(self.path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM account_domain_entities WHERE " + " AND ".join(clauses) +
                " ORDER BY entity_id" + paging, args,
            ).fetchall()
        return [_decode(row["payload_json"])["factor"] for row in rows]

    def cursor(self, scope_key: str) -> int:
        with connect_sqlite(self.path) as conn:
            row = conn.execute(
                "SELECT remote_revision FROM account_domain_cursors WHERE scope_key=?",
                (scope_key,),
            ).fetchone()
        return int(row["remote_revision"]) if row else 0

    def advance_cursor(self, scope_key: str, revision: int) -> None:
        with connect_sqlite(self.path) as conn:
            conn.execute(
                """
                INSERT INTO account_domain_cursors(scope_key, remote_revision, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                    remote_revision=MAX(remote_revision, excluded.remote_revision),
                    updated_at=excluded.updated_at
                """,
                (scope_key, int(revision), time.time()),
            )

    def get_entity(self, principal: str, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        """Read a single identity, including tombstones, through the primary key."""
        with connect_sqlite(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM account_domain_entities WHERE principal=? AND entity_type=? AND entity_id=?",
                (principal, entity_type, entity_id),
            ).fetchone()
        return _entity_row(row) if row is not None else None

    def list_entities(
        self,
        *,
        principal: str = "",
        entity_type: str = "",
        include_shared: bool = True,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = [] if include_deleted else ["deleted=0"]
        if entity_type != "factor_catalog_entry":
            clauses.append("entity_type != 'factor_catalog_entry'")
        params: list[Any] = []
        if principal:
            if include_shared:
                clauses.append("(principal=? OR json_extract(payload_json, '$.visibility')='public' OR (json_extract(payload_json, '$.visibility')='authorized' AND instr(payload_json, ?) > 0))")
                params.extend((principal, f'"{principal}"'))
            else:
                clauses.append("principal=?")
                params.append(principal)
        if entity_type:
            clauses.append("entity_type=?")
            params.append(entity_type)
        with connect_sqlite(self.path) as conn:
            rows = conn.execute(
                f"""
                SELECT principal, entity_type, entity_id, payload_json,
                       deleted, remote_revision, origin_manager_id, updated_at
                FROM account_domain_entities
                {('WHERE ' + ' AND '.join(clauses)) if clauses else ''}
                ORDER BY updated_at DESC, entity_id
                """,
                tuple(params),
            ).fetchall()
        return [_entity_row(row) for row in rows]

    def conflicts(self, *, principal: str = "", status: str = "open") -> list[dict[str, Any]]:
        clauses = ["status=?"]
        params: list[Any] = [status]
        if principal:
            clauses.append("principal=?")
            params.append(principal)
        with connect_sqlite(self.path) as conn:
            rows = conn.execute(
                f"SELECT * FROM account_domain_conflicts WHERE {' AND '.join(clauses)} ORDER BY created_at",
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]


def _materialize_factor_entries(conn, principal, entity_type, entity_id, payload, deleted, manager_id):
    """Normalize registered rows in the existing mirror, separately from authoring JSON.

    These local read projections never enter the outbox. The source config and
    its frozen row projections change in one transaction; an unresolved draft
    retains the last successfully materialized catalog until it can be frozen.
    """
    if entity_type != "factor_param_config":
        return
    if not deleted and not isinstance(payload.get("resolved_factors"), list):
        return
    from server.manager.services.account_domain_projection import factor_rows_from_account_entities
    rows = [] if deleted else factor_rows_from_account_entities([{
        "principal": principal, "entity_id": entity_id, "payload": payload,
    }], principal)
    # A partial source-dependent rebuild cannot remove registered objects.
    if not deleted and len(rows) < len(payload.get("params_list") or []):
        return
    previous = {row[0] for row in conn.execute(
        "SELECT entity_id FROM account_domain_entities WHERE principal=? AND entity_type='factor_catalog_entry' "
        "AND json_extract(payload_json, '$.source_config_id')=?", (principal, entity_id),
    )}
    retained = set()
    for factor in rows:
        identifier = hashlib.sha256(_encode({"config": entity_id, "ref": factor["factor_ref"]}).encode()).hexdigest()
        retained.add(identifier)
        value = _encode({"source_config_id": entity_id, "factor": factor})
        conn.execute(
            "INSERT INTO account_domain_entities(principal, entity_type, entity_id, payload_json, deleted, origin_manager_id, updated_at) "
            "VALUES (?, 'factor_catalog_entry', ?, ?, 0, ?, ?) "
            "ON CONFLICT(principal, entity_type, entity_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at "
            "WHERE payload_json != excluded.payload_json",
            (principal, identifier, value, manager_id, time.time()),
        )
    conn.executemany(
        "DELETE FROM account_domain_entities WHERE principal=? AND entity_type='factor_catalog_entry' AND entity_id=?",
        [(principal, identifier) for identifier in previous-retained],
    )


def _record_conflict(conn: sqlite3.Connection, item: dict[str, Any], remote: dict[str, Any]) -> None:
    """One durable observation per local value and authority revision, even on replay."""
    values = (
        item["principal"], item["entity_type"], item["entity_id"],
        _encode(item.get("payload") or {}), _encode(remote.get("payload") or {}),
        int(bool(remote.get("deleted"))), int(remote.get("revision") or 0),
    )
    exists = conn.execute(
        "SELECT 1 FROM account_domain_conflicts WHERE principal=? AND entity_type=? AND entity_id=? "
        "AND local_payload_json=? AND remote_payload_json=? AND remote_deleted=? AND remote_revision=? "
        "AND status='open' LIMIT 1", values,
    ).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO account_domain_conflicts(conflict_id, principal, entity_type, entity_id, "
            "local_payload_json, remote_payload_json, remote_deleted, remote_revision, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, *values, time.time()),
        )


def _encode(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(value: object) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _outbox_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "operation_id": str(row["operation_id"]),
        "principal": str(row["principal"]),
        "entity_type": str(row["entity_type"]),
        "entity_id": str(row["entity_id"]),
        "payload": _decode(row["payload_json"]),
        "deleted": bool(row["deleted"]),
        "base_revision": row["base_revision"],
        "attempts": int(row["attempts"] or 0),
        "last_error": str(row["last_error"] or ""),
    }


def _entity_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "principal": str(row["principal"]),
        "entity_type": str(row["entity_type"]),
        "entity_id": str(row["entity_id"]),
        "payload": _decode(row["payload_json"]),
        "deleted": bool(row["deleted"]),
        "revision": row["remote_revision"],
        "origin_manager_id": str(row["origin_manager_id"] or ""),
        "updated_at": float(row["updated_at"] or 0),
    }

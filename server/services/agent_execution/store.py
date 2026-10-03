"""Durable identity records for resumable Agent executions."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from typing import Any

import settings as Settings

from .schema import connect_agent_execution, ensure_schema


_STORE_CACHE: dict[str, AgentExecutionStore] = {}


class AgentExecutionStore:
    """Persist identity metadata without token or provider accounting."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if not self._schema_ready:
                ensure_schema(self.db_path)
                self._schema_ready = True

    def register_execution(
        self,
        *,
        owner_user_id: str,
        execution_id: str,
        agent_id: str,
        actor_role: str,
        authority_scope: str,
        agent_principal_hash: str,
        lineage_hash: str,
        task_ref: str = "",
        purpose: str = "",
    ) -> dict[str, Any]:
        values = {
            "owner_user_id": owner_user_id,
            "execution_id": execution_id,
            "agent_id": agent_id,
            "actor_role": actor_role,
            "authority_scope": authority_scope,
            "task_ref": task_ref,
            "purpose": purpose,
            "agent_principal_hash": agent_principal_hash,
            "lineage_hash": lineage_hash,
        }
        for field, value in values.items():
            if not isinstance(value, str) or not value.strip():
                if field in {"task_ref", "purpose"}:
                    continue
                raise ValueError(f"{field} is required")
        _require_sha256("agent_principal_hash", agent_principal_hash)
        _require_sha256("lineage_hash", lineage_hash)
        now = time.time()
        with connect_agent_execution(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM agent_executions "
                "WHERE owner_user_id=? AND execution_id=?",
                (owner_user_id, execution_id),
            ).fetchone()
            if existing is not None:
                current = _row_value(existing)
                comparable = {
                    key: current[key]
                    for key in values
                }
                if comparable != values:
                    raise ValueError(
                        "Agent execution identity does not match the "
                        "existing execution"
                    )
                return current
            conn.execute(
                """
                INSERT INTO agent_executions (
                    execution_id, owner_user_id, agent_id, actor_role,
                    authority_scope, task_ref, purpose,
                    agent_principal_hash, lineage_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    owner_user_id,
                    agent_id,
                    actor_role,
                    authority_scope,
                    task_ref,
                    purpose,
                    agent_principal_hash,
                    lineage_hash,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_executions "
                "WHERE owner_user_id=? AND execution_id=?",
                (owner_user_id, execution_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("Agent execution was not persisted")
        return _row_value(row)

    def load_execution(
        self,
        *,
        owner_user_id: str,
        execution_id: str,
    ) -> dict[str, Any]:
        with connect_agent_execution(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM agent_executions "
                "WHERE owner_user_id=? AND execution_id=?",
                (owner_user_id, execution_id),
            ).fetchone()
        if row is None:
            raise KeyError("Agent execution not found")
        return _row_value(row)

    def load_executions(
        self,
        *,
        owner_user_id: str,
        execution_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        unique_ids = list(dict.fromkeys(execution_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        with connect_agent_execution(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM agent_executions "
                f"WHERE owner_user_id=? AND execution_id IN ({placeholders})",
                (owner_user_id, *unique_ids),
            ).fetchall()
        return {
            str(row["execution_id"]): _row_value(row)
            for row in rows
        }


def database_path() -> Path:
    configured = os.environ.get("AGENT_EXECUTION_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    cache_path = Path(Settings.CACHE_DB_PATH)
    return cache_path.with_name(
        f"{cache_path.stem}.agent-execution"
        f"{cache_path.suffix or '.sqlite'}"
    )


def get_store() -> AgentExecutionStore:
    path = str(database_path())
    store = _STORE_CACHE.get(path)
    if store is None:
        store = AgentExecutionStore(path)
        _STORE_CACHE[path] = store
    return store


def clear_store_cache() -> None:
    _STORE_CACHE.clear()


def _row_value(row: Any) -> dict[str, Any]:
    return {
        "execution_id": str(row["execution_id"]),
        "owner_user_id": str(row["owner_user_id"]),
        "agent_id": str(row["agent_id"]),
        "actor_role": str(row["actor_role"]),
        "authority_scope": str(row["authority_scope"]),
        "task_ref": str(row["task_ref"]),
        "purpose": str(row["purpose"]),
        "agent_principal_hash": str(row["agent_principal_hash"]),
        "lineage_hash": str(row["lineage_hash"]),
        "created_at": float(row["created_at"]),
    }


def _require_sha256(field: str, value: str) -> None:
    if (
        len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be sha256")

"""Local runtime ownership and single-Agent Profile claims.

This state is intentionally Manager-local.  A server Profile is bound to one
server, while a client Profile is bound to one client device.  The same
Profile workspace is used directly; no Agent copy or temporary worktree is
created by this store.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from tools.data.sqlite.db import connect_sqlite


RUNTIME_TABLE = "manager_profile_runtime_bindings"
CLAIM_TABLE = "manager_profile_agent_claims"


class ProfileRuntimeError(ValueError):
    """A Profile runtime binding or claim is invalid."""


class ProfileClaimConflict(ProfileRuntimeError):
    """The Profile is already claimed by another live Agent."""

    def __init__(self, claim: dict[str, Any]) -> None:
        super().__init__("research identity is already claimed")
        self.claim = claim


class ProfileRuntimeStore:
    """Persist runtime bindings and leases in the existing Manager SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = connect_sqlite(self.db_path, timeout=5.0)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {RUNTIME_TABLE} (
                    principal TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    runtime_kind TEXT NOT NULL,
                    executor_id TEXT NOT NULL,
                    workspace_relpath TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (principal, profile_id)
                )
                """
            )
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {CLAIM_TABLE} (
                    claim_id TEXT PRIMARY KEY,
                    principal TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    runtime_kind TEXT NOT NULL,
                    executor_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL DEFAULT '',
                    agent_runtime TEXT NOT NULL DEFAULT 'codex',
                    provider_protocol TEXT NOT NULL DEFAULT 'openai_responses',
                    provider_model TEXT NOT NULL DEFAULT '',
                    provider_config_version REAL NOT NULL DEFAULT 0,
                    claimed_at REAL NOT NULL,
                    last_heartbeat_at REAL NOT NULL,
                    released_at REAL,
                    status TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row[1])
                for row in db.execute(f"PRAGMA table_info({CLAIM_TABLE})").fetchall()
            }
            additions = {
                "agent_runtime": "TEXT NOT NULL DEFAULT 'codex'",
                "provider_protocol": "TEXT NOT NULL DEFAULT 'openai_responses'",
                "provider_model": "TEXT NOT NULL DEFAULT ''",
                "provider_config_version": "REAL NOT NULL DEFAULT 0",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    db.execute(
                        f"ALTER TABLE {CLAIM_TABLE} ADD COLUMN {name} {declaration}"
                    )
            db.execute(
                f"""CREATE UNIQUE INDEX IF NOT EXISTS {CLAIM_TABLE}_active_profile
                    ON {CLAIM_TABLE}(principal, profile_id)
                    WHERE released_at IS NULL"""
            )
            db.execute(
                f"""CREATE INDEX IF NOT EXISTS {CLAIM_TABLE}_heartbeat
                    ON {CLAIM_TABLE}(last_heartbeat_at, released_at)"""
            )

    @staticmethod
    def _text(value: object, field: str, *, required: bool = True) -> str:
        result = str(value or "").strip()
        if required and not result:
            raise ProfileRuntimeError(f"{field} is required")
        if len(result) > 256:
            raise ProfileRuntimeError(f"{field} is too long")
        return result

    @classmethod
    def _runtime(cls, value: object) -> str:
        runtime = cls._text(value, "runtime_kind")
        if runtime not in {"client", "server"}:
            raise ProfileRuntimeError("runtime_kind is unsupported")
        return runtime

    @staticmethod
    def _runtime_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "profile_id": str(row["profile_id"] or ""),
            "runtime_kind": str(row["runtime_kind"] or ""),
            "executor_id": str(row["executor_id"] or ""),
            "workspace_relpath": str(row["workspace_relpath"] or ""),
            "updated_at": float(row["updated_at"] or 0),
        }

    @staticmethod
    def _claim_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "claim_id": str(row["claim_id"] or ""),
            "principal": str(row["principal"] or ""),
            "profile_id": str(row["profile_id"] or ""),
            "runtime_kind": str(row["runtime_kind"] or ""),
            "executor_id": str(row["executor_id"] or ""),
            "agent_id": str(row["agent_id"] or ""),
            "provider_id": str(row["provider_id"] or ""),
            "agent_runtime": str(row["agent_runtime"] or "codex"),
            "provider_protocol": str(
                row["provider_protocol"] or "openai_responses"
            ),
            "provider_model": str(row["provider_model"] or ""),
            "provider_config_version": float(
                row["provider_config_version"] or 0
            ),
            "claimed_at": float(row["claimed_at"] or 0),
            "last_heartbeat_at": float(row["last_heartbeat_at"] or 0),
            "status": str(row["status"] or ""),
        }

    def runtime(self, principal: str, profile_id: str) -> dict[str, Any] | None:
        owner = self._text(principal, "principal")
        identifier = self._text(profile_id, "profile_id")
        with self._connection() as db:
            row = db.execute(
                f"SELECT * FROM {RUNTIME_TABLE} WHERE principal = ? AND profile_id = ?",
                (owner, identifier),
            ).fetchone()
        return self._runtime_row(row)

    def runtimes(self, principal: str) -> dict[str, dict[str, Any]]:
        owner = self._text(principal, "principal")
        with self._connection() as db:
            rows = db.execute(
                f"SELECT * FROM {RUNTIME_TABLE} WHERE principal = ?",
                (owner,),
            ).fetchall()
        return {
            str(row["profile_id"]): self._runtime_row(row) or {}
            for row in rows
        }

    def bind(
        self,
        principal: str,
        profile_id: str,
        *,
        runtime_kind: str,
        executor_id: str,
        workspace_relpath: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        owner = self._text(principal, "principal")
        identifier = self._text(profile_id, "profile_id")
        runtime = self._runtime(runtime_kind)
        executor = self._text(executor_id, "executor_id")
        relative = self._text(workspace_relpath, "workspace_relpath")
        current = float(time.time() if now is None else now)
        with self._connection() as db:
            active = db.execute(
                f"""SELECT * FROM {CLAIM_TABLE}
                    WHERE principal = ? AND profile_id = ? AND released_at IS NULL""",
                (owner, identifier),
            ).fetchone()
            if active is not None:
                raise ProfileRuntimeError("release the active Agent before changing Profile runtime")
            db.execute(
                f"""INSERT INTO {RUNTIME_TABLE} (
                    principal, profile_id, runtime_kind, executor_id,
                    workspace_relpath, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(principal, profile_id) DO UPDATE SET
                    runtime_kind=excluded.runtime_kind,
                    executor_id=excluded.executor_id,
                    workspace_relpath=excluded.workspace_relpath,
                    updated_at=excluded.updated_at""",
                (owner, identifier, runtime, executor, relative, current),
            )
            row = db.execute(
                f"SELECT * FROM {RUNTIME_TABLE} WHERE principal = ? AND profile_id = ?",
                (owner, identifier),
            ).fetchone()
        value = self._runtime_row(row)
        if value is None:  # pragma: no cover - guarded by the write above
            raise ProfileRuntimeError("Profile runtime was not saved")
        return value

    def active_claim(
        self,
        principal: str,
        profile_id: str,
        *,
        now: float | None = None,
        lease_seconds: float = 120.0,
    ) -> dict[str, Any] | None:
        owner = self._text(principal, "principal")
        identifier = self._text(profile_id, "profile_id")
        current = float(time.time() if now is None else now)
        cutoff = current - max(1.0, float(lease_seconds))
        with self._connection() as db:
            self._expire(db, cutoff, current)
            row = db.execute(
                f"""SELECT * FROM {CLAIM_TABLE}
                    WHERE principal = ? AND profile_id = ? AND released_at IS NULL""",
                (owner, identifier),
            ).fetchone()
        return self._claim_row(row)

    @staticmethod
    def _expire(db: sqlite3.Connection, cutoff: float, now: float) -> None:
        db.execute(
            f"""UPDATE {CLAIM_TABLE}
                SET released_at = ?, status = 'expired'
                WHERE released_at IS NULL AND status = 'claimed'
                  AND last_heartbeat_at < ?""",
            (now, cutoff),
        )

    def claim(
        self,
        principal: str,
        profile_id: str,
        *,
        runtime_kind: str,
        executor_id: str,
        provider_id: str = "",
        agent_runtime: str = "codex",
        provider_protocol: str = "openai_responses",
        provider_model: str = "",
        provider_config_version: float = 0,
        agent_id: str = "",
        now: float | None = None,
        lease_seconds: float = 120.0,
    ) -> dict[str, Any]:
        owner = self._text(principal, "principal")
        identifier = self._text(profile_id, "profile_id")
        runtime = self._runtime(runtime_kind)
        executor = self._text(executor_id, "executor_id")
        provider = self._text(provider_id, "provider_id", required=False)
        frozen_runtime = self._text(agent_runtime, "agent_runtime")
        frozen_protocol = self._text(provider_protocol, "provider_protocol")
        frozen_model = self._text(provider_model, "provider_model", required=False)
        frozen_version = float(provider_config_version or 0)
        agent = self._text(agent_id, "agent_id", required=False)
        current = float(time.time() if now is None else now)
        cutoff = current - max(1.0, float(lease_seconds))
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db, cutoff, current)
            active = db.execute(
                f"""SELECT * FROM {CLAIM_TABLE}
                    WHERE principal = ? AND profile_id = ? AND released_at IS NULL""",
                (owner, identifier),
            ).fetchone()
            existing = self._claim_row(active)
            if existing is not None:
                if (
                    existing["runtime_kind"] == runtime
                    and existing["executor_id"] == executor
                    and (not agent or existing["agent_id"] == agent)
                    and existing["provider_id"] == provider
                    and existing["agent_runtime"] == frozen_runtime
                    and existing["provider_protocol"] == frozen_protocol
                    and existing["provider_model"] == frozen_model
                    and existing["provider_config_version"] == frozen_version
                ):
                    db.execute(
                        f"""UPDATE {CLAIM_TABLE}
                            SET last_heartbeat_at = ?, status = 'claimed'
                            WHERE claim_id = ?""",
                        (current, existing["claim_id"]),
                    )
                    refreshed = db.execute(
                        f"SELECT * FROM {CLAIM_TABLE} WHERE claim_id = ?",
                        (existing["claim_id"],),
                    ).fetchone()
                    value = self._claim_row(refreshed)
                    if value is None:  # pragma: no cover
                        raise ProfileRuntimeError("Profile claim disappeared")
                    return value
                raise ProfileClaimConflict(existing)
            claim_id = "claim_" + secrets.token_urlsafe(12)
            if not agent:
                agent = "agent_" + secrets.token_urlsafe(9)
            db.execute(
                f"""INSERT INTO {CLAIM_TABLE} (
                    claim_id, principal, profile_id, runtime_kind,
                    executor_id, agent_id, provider_id, agent_runtime,
                    provider_protocol, provider_model, provider_config_version, claimed_at,
                    last_heartbeat_at, released_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'claimed')""",
                (
                    claim_id, owner, identifier, runtime, executor, agent,
                    provider, frozen_runtime, frozen_protocol, frozen_model,
                    frozen_version, current, current,
                ),
            )
            row = db.execute(
                f"SELECT * FROM {CLAIM_TABLE} WHERE claim_id = ?",
                (claim_id,),
            ).fetchone()
        value = self._claim_row(row)
        if value is None:  # pragma: no cover - guarded by the insert above
            raise ProfileRuntimeError("Profile claim was not saved")
        return value

    def freeze_legacy_provider_binding(
        self,
        claim_id: str,
        *,
        provider_id: str,
        agent_runtime: str,
        provider_protocol: str,
        provider_model: str,
        provider_config_version: float,
    ) -> dict[str, Any]:
        """Freeze one pre-capability claim exactly once."""
        identifier = self._text(claim_id, "claim_id")
        provider = self._text(provider_id, "provider_id")
        runtime = self._text(agent_runtime, "agent_runtime")
        protocol = self._text(provider_protocol, "provider_protocol")
        model = self._text(provider_model, "provider_model")
        version = float(provider_config_version or 0)
        if version <= 0:
            raise ProfileRuntimeError("provider_config_version is required")
        with self._connection() as db:
            cursor = db.execute(
                f"""UPDATE {CLAIM_TABLE}
                    SET agent_runtime = ?, provider_protocol = ?,
                        provider_model = ?, provider_config_version = ?
                    WHERE claim_id = ? AND provider_id = ?
                      AND provider_config_version = 0
                      AND released_at IS NULL""",
                (runtime, protocol, model, version, identifier, provider),
            )
            if cursor.rowcount != 1:
                raise ProfileClaimConflict(
                    "Agent provider binding changed while it was being frozen"
                )
            row = db.execute(
                f"SELECT * FROM {CLAIM_TABLE} WHERE claim_id = ?",
                (identifier,),
            ).fetchone()
        value = self._claim_row(row)
        if value is None:  # pragma: no cover
            raise ProfileRuntimeError("Profile claim disappeared")
        return value

    def heartbeat(
        self,
        principal: str,
        claim_id: str,
        *,
        agent_id: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        owner = self._text(principal, "principal")
        identifier = self._text(claim_id, "claim_id")
        agent = self._text(agent_id, "agent_id")
        current = float(time.time() if now is None else now)
        with self._connection() as db:
            cursor = db.execute(
                f"""UPDATE {CLAIM_TABLE}
                    SET last_heartbeat_at = ?, status = 'claimed'
                    WHERE claim_id = ? AND principal = ? AND agent_id = ?
                      AND released_at IS NULL""",
                (current, identifier, owner, agent),
            )
            if not cursor.rowcount:
                raise ProfileRuntimeError("active Profile claim was not found")
            row = db.execute(
                f"SELECT * FROM {CLAIM_TABLE} WHERE claim_id = ?",
                (identifier,),
            ).fetchone()
        value = self._claim_row(row)
        if value is None:  # pragma: no cover
            raise ProfileRuntimeError("Profile claim disappeared")
        return value

    def release(
        self,
        principal: str,
        claim_id: str,
        *,
        agent_id: str = "",
        force: bool = False,
        now: float | None = None,
    ) -> bool:
        owner = self._text(principal, "principal")
        identifier = self._text(claim_id, "claim_id")
        agent = self._text(agent_id, "agent_id", required=False)
        current = float(time.time() if now is None else now)
        clauses = ["claim_id = ?", "principal = ?", "released_at IS NULL"]
        parameters: list[object] = [identifier, owner]
        if not force:
            clauses.append("agent_id = ?")
            parameters.append(agent)
        with self._connection() as db:
            cursor = db.execute(
                f"""UPDATE {CLAIM_TABLE}
                    SET released_at = ?, status = 'released'
                    WHERE {' AND '.join(clauses)}""",
                [current, *parameters],
            )
        return bool(cursor.rowcount)

    def pause(
        self,
        principal: str,
        claim_id: str,
        *,
        agent_id: str = "",
        force: bool = False,
        now: float | None = None,
    ) -> bool:
        """Pause a Manager-owned Agent without releasing its Profile claim.

        An explicit user release remains the only operation that removes
        ownership.  A paused claim is intentionally not expired by the lease
        sweeper; starting the same Profile resumes it and refreshes its
        heartbeat.  This also lets a server Agent be stopped for maintenance
        without forcing the user through the binding flow again.
        """
        owner = self._text(principal, "principal")
        identifier = self._text(claim_id, "claim_id")
        agent = self._text(agent_id, "agent_id", required=False)
        current = float(time.time() if now is None else now)
        clauses = ["claim_id = ?", "principal = ?", "released_at IS NULL"]
        parameters: list[object] = [identifier, owner]
        if not force:
            clauses.append("agent_id = ?")
            parameters.append(agent)
        with self._connection() as db:
            cursor = db.execute(
                f"""UPDATE {CLAIM_TABLE}
                    SET status = 'stopped', last_heartbeat_at = ?
                    WHERE {' AND '.join(clauses)}""",
                [current, *parameters],
            )
        return bool(cursor.rowcount)

    def claims(
        self,
        principal: str,
        *,
        now: float | None = None,
        lease_seconds: float = 120.0,
    ) -> list[dict[str, Any]]:
        owner = self._text(principal, "principal")
        current = float(time.time() if now is None else now)
        cutoff = current - max(1.0, float(lease_seconds))
        with self._connection() as db:
            self._expire(db, cutoff, current)
            rows = db.execute(
                f"""SELECT * FROM {CLAIM_TABLE}
                    WHERE principal = ? AND released_at IS NULL
                    ORDER BY claimed_at DESC""",
                (owner,),
            ).fetchall()
        return [self._claim_row(row) for row in rows if row is not None]

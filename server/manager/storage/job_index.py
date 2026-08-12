"""Small manager-owned index for cross-port job summaries.

Service instances remain authoritative for job details.  This index only
stores the latest summary observed by Manager, so a slow or stopped port does
not make the already-known list disappear.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


class ManagerJobIndex:
    """Manager-local job projection plus a durable control-plane outbox.

    The service database remains authoritative for detailed job data.  This
    store is deliberately a local projection: it can be rebuilt or caught up
    from the control events without copying a SQLite file between hosts.
    ``server_id`` identifies the event stream owned by this Manager.
    """

    MAX_EVENT_BATCH = 200

    def __init__(self, path: Path, *, server_id: str = "local") -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.server_id = str(server_id or "local").strip() or "local"
        self._lock = threading.RLock()
        with self._connection() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    principal TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    job_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT '',
                    updated_order REAL NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL,
                    source_server_id TEXT NOT NULL DEFAULT '',
                    source_event_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (principal, port, job_id)
                )"""
            )
            self._ensure_column(db, "jobs", "source_server_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "jobs", "source_event_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "jobs", "updated_order", "REAL NOT NULL DEFAULT 0")
            db.execute(
                """CREATE INDEX IF NOT EXISTS jobs_order
                   ON jobs(principal, updated_at DESC)"""
            )
            db.execute(
                """CREATE INDEX IF NOT EXISTS jobs_updated_order
                   ON jobs(principal, updated_order DESC, updated_at DESC)"""
            )
            self._backfill_updated_order(db)
            db.execute(
                """CREATE TABLE IF NOT EXISTS manager_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS control_events (
                    event_id TEXT PRIMARY KEY,
                    source_server_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    audience TEXT NOT NULL DEFAULT '[]',
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(source_server_id, sequence)
                )"""
            )
            db.execute(
                """CREATE INDEX IF NOT EXISTS control_events_source_order
                   ON control_events(source_server_id, sequence)"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS control_sync_cursors (
                    source_server_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS run_routing (
                    run_id TEXT PRIMARY KEY,
                    principal TEXT NOT NULL DEFAULT '',
                    origin_server_id TEXT NOT NULL,
                    execution_server_id TEXT NOT NULL,
                    execution_port INTEGER NOT NULL,
                    execution_branch TEXT NOT NULL DEFAULT '',
                    execution_revision TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                )"""
            )

    @staticmethod
    def _ensure_column(
        db: sqlite3.Connection,
        table: str,
        name: str,
        definition: str,
    ) -> None:
        columns = {
            str(row[1])
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if name not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _backfill_updated_order(self, db: sqlite3.Connection) -> None:
        rows = db.execute(
            """SELECT principal, port, job_id, updated_at, payload
               FROM jobs WHERE updated_order=0"""
        ).fetchall()
        for row in rows:
            updated_at = row["updated_at"]
            try:
                payload = json.loads(row["payload"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and not str(updated_at or "").strip():
                updated_at = payload.get("updated_at")
            order = self._updated_timestamp(updated_at)
            if order is None:
                continue
            db.execute(
                """UPDATE jobs SET updated_order=?
                   WHERE principal=? AND port=? AND job_id=?""",
                (
                    order, str(row["principal"]), int(row["port"]),
                    str(row["job_id"]),
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Close each connection after its transaction scope completes."""
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _routing_for_run(
        self,
        db: sqlite3.Connection,
        run_id: str,
    ) -> sqlite3.Row | None:
        if not run_id:
            return None
        return db.execute(
            """SELECT run_id, principal, origin_server_id,
                      execution_server_id, execution_port,
                      execution_branch, execution_revision
                 FROM run_routing WHERE run_id=?""",
            (run_id,),
        ).fetchone()

    @staticmethod
    def _with_routing(
        job: dict[str, Any],
        routing: sqlite3.Row | None,
    ) -> dict[str, Any]:
        if routing is None:
            return dict(job)
        value = dict(job)
        value.update({
            "origin_server_id": str(routing["origin_server_id"] or ""),
            "execution_server_id": str(routing["execution_server_id"] or ""),
            "execution_port": int(routing["execution_port"] or 0),
            "execution_branch": str(routing["execution_branch"] or ""),
            "execution_revision": str(routing["execution_revision"] or ""),
        })
        return value

    @staticmethod
    def _audience(job: dict[str, Any]) -> list[str]:
        audience = {
            str(job.get(key) or "").strip()
            for key in (
                "server_id",
                "origin_server_id",
                "execution_server_id",
            )
            if str(job.get(key) or "").strip()
        }
        return sorted(audience)

    @staticmethod
    def _updated_timestamp(value: object) -> float | None:
        raw = str(value or "")
        try:
            return float(raw)
        except (TypeError, ValueError):
            try:
                normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
                return datetime.fromisoformat(normalized).timestamp()
            except (TypeError, ValueError, OverflowError):
                return None

    @classmethod
    def _updated_order(cls, value: object) -> tuple[int, object]:
        timestamp = cls._updated_timestamp(value)
        return (0, timestamp) if timestamp is not None else (1, str(value or ""))

    def _next_sequence(self, db: sqlite3.Connection) -> int:
        row = db.execute(
            "SELECT value FROM manager_meta WHERE key='event_sequence'"
        ).fetchone()
        sequence = int(row[0] or 0) + 1 if row is not None else 1
        db.execute(
            """INSERT INTO manager_meta(key, value) VALUES ('event_sequence', ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (str(sequence),),
        )
        return sequence

    def _append_event(
        self,
        db: sqlite3.Connection,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        principal: str,
        job: dict[str, Any] | None = None,
        routing: dict[str, Any] | None = None,
        public: bool = True,
    ) -> dict[str, Any]:
        sequence = self._next_sequence(db)
        audience = self._audience(job or routing or {})
        event: dict[str, Any] = {
            "event_id": f"{self.server_id}:{sequence}",
            "source_server_id": self.server_id,
            "sequence": sequence,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "principal": str(principal or ""),
            "audience": audience,
            "public": bool(public),
            "occurred_at": time.time(),
        }
        if job is not None:
            event["job"] = dict(job)
        if routing is not None:
            event["routing"] = dict(routing)
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        db.execute(
            """INSERT INTO control_events(
                    event_id, source_server_id, sequence, event_type,
                    entity_type, entity_id, audience, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["event_id"], self.server_id, sequence, event_type,
                entity_type, entity_id,
                json.dumps(audience, ensure_ascii=False, separators=(",", ":")),
                encoded, float(event["occurred_at"]),
            ),
        )
        return event

    def _upsert_job_row(
        self,
        db: sqlite3.Connection,
        principal: str,
        job: dict[str, Any],
        *,
        source_server_id: str = "",
        source_event_id: str = "",
        reject_older: bool = False,
    ) -> bool:
        job_id = str(job.get("job_id") or "").strip()
        port = job.get("port")
        if not job_id or not isinstance(port, int):
            return False
        payload = json.dumps(job, ensure_ascii=False, separators=(",", ":"))
        existing = db.execute(
            """SELECT updated_at, payload FROM jobs
               WHERE principal=? AND port=? AND job_id=?""",
            (principal, port, job_id),
        ).fetchone()
        updated_at = str(job.get("updated_at") or "")
        updated_order = self._updated_timestamp(updated_at) or 0.0
        if reject_older and existing is not None:
            if self._updated_order(updated_at) < self._updated_order(existing["updated_at"]):
                return False
            if payload == str(existing["payload"] or ""):
                return False
        db.execute(
            """INSERT INTO jobs(
                    principal, port, job_id, updated_at, updated_order, payload,
                    source_server_id, source_event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(principal, port, job_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    updated_order=excluded.updated_order,
                    payload=excluded.payload,
                    source_server_id=excluded.source_server_id,
                    source_event_id=excluded.source_event_id""",
            (
                principal, port, job_id, updated_at, updated_order, payload,
                str(source_server_id or ""), str(source_event_id or ""),
            ),
        )
        return True

    def upsert(
        self,
        principal: str,
        jobs: Iterable[dict[str, Any]],
        *,
        emit_events: bool = True,
    ) -> None:
        values = []
        for job in jobs:
            job_id = str(job.get("job_id") or "").strip()
            port = job.get("port")
            if not job_id or not isinstance(port, int):
                continue
            values.append((job_id, port, dict(job)))
        if not values:
            return
        with self._lock, self._connection() as db:
            for job_id, port, raw_job in values:
                job = self._with_routing(
                    raw_job,
                    self._routing_for_run(db, str(raw_job.get("run_id") or "")),
                )
                existing = db.execute(
                    """SELECT payload FROM jobs
                       WHERE principal=? AND port=? AND job_id=?""",
                    (str(principal), port, job_id),
                ).fetchone()
                changed = self._upsert_job_row(
                    db, str(principal), job,
                    source_server_id=self.server_id,
                )
                if (
                    emit_events
                    and changed
                    and (
                        existing is None
                        or str(existing["payload"] or "")
                        != json.dumps(job, ensure_ascii=False, separators=(",", ":"))
                    )
                ):
                    self._append_event(
                        db,
                        event_type="job.updated",
                        entity_type="job",
                        entity_id=job_id,
                        principal=str(principal),
                        job=job,
                    )

    def record_run_routing(
        self,
        *,
        run_id: str,
        principal: str,
        origin_server_id: str,
        execution_server_id: str,
        execution_port: int,
        execution_branch: str = "",
        execution_revision: str = "",
    ) -> dict[str, Any] | None:
        """Persist a run placement and enqueue one idempotent routing event."""
        run_id = str(run_id or "").strip()
        origin_server_id = str(origin_server_id or "").strip()
        execution_server_id = str(execution_server_id or "").strip()
        if not run_id or not origin_server_id or not execution_server_id:
            return None
        port = int(execution_port)
        routing = {
            "run_id": run_id,
            "principal": str(principal or ""),
            "origin_server_id": origin_server_id,
            "execution_server_id": execution_server_id,
            "execution_port": port,
            "execution_branch": str(execution_branch or ""),
            "execution_revision": str(execution_revision or ""),
        }
        with self._lock, self._connection() as db:
            old = db.execute(
                """SELECT principal, origin_server_id, execution_server_id,
                          execution_port, execution_branch, execution_revision
                     FROM run_routing WHERE run_id=?""",
                (run_id,),
            ).fetchone()
            comparable = (
                str(old["principal"] or ""),
                str(old["origin_server_id"] or ""),
                str(old["execution_server_id"] or ""),
                int(old["execution_port"] or 0),
                str(old["execution_branch"] or ""),
                str(old["execution_revision"] or ""),
            ) if old is not None else None
            current = (
                routing["principal"], routing["origin_server_id"],
                routing["execution_server_id"], routing["execution_port"],
                routing["execution_branch"], routing["execution_revision"],
            )
            if comparable == current:
                return None
            db.execute(
                """INSERT INTO run_routing(
                        run_id, principal, origin_server_id,
                        execution_server_id, execution_port,
                        execution_branch, execution_revision, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        principal=excluded.principal,
                        origin_server_id=excluded.origin_server_id,
                        execution_server_id=excluded.execution_server_id,
                        execution_port=excluded.execution_port,
                        execution_branch=excluded.execution_branch,
                        execution_revision=excluded.execution_revision,
                        updated_at=excluded.updated_at""",
                (
                    run_id, routing["principal"], routing["origin_server_id"],
                    routing["execution_server_id"], routing["execution_port"],
                    routing["execution_branch"], routing["execution_revision"],
                    time.time(),
                ),
            )
            self._enrich_existing_run_jobs(db, run_id, routing)
            return self._append_event(
                db,
                event_type="run.routed",
                entity_type="run",
                entity_id=run_id,
                principal=str(principal),
                routing=routing,
            )

    def _enrich_existing_run_jobs(
        self,
        db: sqlite3.Connection,
        run_id: str,
        routing: dict[str, Any],
    ) -> None:
        rows = db.execute(
            "SELECT principal, port, job_id, payload FROM jobs"
        ).fetchall()
        for row in rows:
            try:
                job = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(job, dict) or str(job.get("run_id") or "") != run_id:
                continue
            enriched = {
                **job,
                "origin_server_id": routing["origin_server_id"],
                "execution_server_id": routing["execution_server_id"],
                "execution_port": routing["execution_port"],
                "execution_branch": routing["execution_branch"],
                "execution_revision": routing["execution_revision"],
            }
            self._upsert_job_row(
                db, str(row["principal"]), enriched,
                source_server_id=self.server_id,
            )

    def events_for_peer(
        self,
        peer_server_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return only events whose task is relevant to the requesting peer."""
        peer = str(peer_server_id or "").strip()
        bounded = max(1, min(int(limit), self.MAX_EVENT_BATCH))
        after = max(0, int(after_sequence))
        scan_limit = min(2000, max(bounded * 8, bounded))
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT sequence, payload FROM control_events
                   WHERE source_server_id=? AND sequence>?
                   ORDER BY sequence ASC LIMIT ?""",
                (self.server_id, after, scan_limit),
            ).fetchall()
        events: list[dict[str, Any]] = []
        next_sequence = after
        for row in rows:
            next_sequence = max(next_sequence, int(row["sequence"] or 0))
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            audience = value.get("audience")
            if peer and isinstance(audience, list) and peer not in {
                str(item) for item in audience
            }:
                continue
            events.append(value)
            if len(events) >= bounded:
                break
        return {
            "success": True,
            "source_server_id": self.server_id,
            "events": events,
            "next_sequence": next_sequence,
            "has_more": len(rows) >= scan_limit,
        }

    def apply_events(self, events: Iterable[dict[str, Any]]) -> int:
        """Apply remote events idempotently without re-emitting them."""
        applied = 0
        with self._lock, self._connection() as db:
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_id = str(event.get("event_id") or "").strip()
                source = str(event.get("source_server_id") or "").strip()
                if not event_id or not source or source == self.server_id:
                    continue
                try:
                    sequence = int(event.get("sequence") or 0)
                except (TypeError, ValueError):
                    continue
                if sequence < 1:
                    continue
                encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                inserted = db.execute(
                    """INSERT OR IGNORE INTO control_events(
                            event_id, source_server_id, sequence,
                            event_type, entity_type, entity_id,
                            audience, payload, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id, source, sequence,
                        str(event.get("event_type") or "unknown"),
                        str(event.get("entity_type") or "unknown"),
                        str(event.get("entity_id") or ""),
                        json.dumps(event.get("audience") or [], separators=(",", ":")),
                        encoded, float(event.get("occurred_at") or time.time()),
                    ),
                ).rowcount
                if not inserted:
                    continue
                applied += 1
                event_type = str(event.get("event_type") or "")
                if event_type == "run.routed":
                    routing = event.get("routing")
                    if isinstance(routing, dict):
                        self._apply_routing(db, routing)
                elif event_type == "job.updated":
                    job = event.get("job")
                    if not isinstance(job, dict):
                        continue
                    principal = str(event.get("principal") or "").strip()
                    if not principal:
                        continue
                    routing = self._routing_for_run(
                        db, str(job.get("run_id") or "")
                    )
                    enriched = self._with_routing(job, routing)
                    self._upsert_job_row(
                        db, principal, enriched,
                        source_server_id=source,
                        source_event_id=event_id,
                        reject_older=True,
                    )
                    if bool(event.get("public", True)):
                        self._upsert_job_row(
                            db, "__public_jobs__", enriched,
                            source_server_id=source,
                            source_event_id=event_id,
                            reject_older=True,
                        )
        return applied

    def reconcile_for_peer(
        self,
        peer_server_id: str,
        *,
        job_ids: Iterable[str] = (),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return current relevant projections for repair after a missed event."""
        peer = str(peer_server_id or "").strip()
        requested = {
            str(value).strip()
            for value in job_ids
            if str(value).strip()
        }
        bounded = max(1, min(int(limit), self.MAX_EVENT_BATCH))
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT principal, payload FROM jobs
                   ORDER BY updated_at DESC LIMIT ?""",
                (min(5000, max(bounded * 10, bounded)),),
            ).fetchall()
        values: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            try:
                job = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(job, dict):
                continue
            job_id = str(job.get("job_id") or "").strip()
            if not job_id or (requested and job_id not in requested):
                continue
            audience = set(self._audience(job))
            if peer and peer not in audience:
                continue
            key = (str(row["principal"] or ""), job_id)
            if key in seen:
                continue
            seen.add(key)
            values.append({
                "principal": str(row["principal"] or ""),
                "job": job,
            })
            if len(values) >= bounded:
                break
        return values

    def apply_reconciliation(
        self,
        projections: Iterable[dict[str, Any]],
        *,
        source_server_id: str,
    ) -> int:
        """Apply a current projection snapshot without creating new events."""
        source = str(source_server_id or "").strip()
        applied = 0
        with self._lock, self._connection() as db:
            for item in projections:
                if not isinstance(item, dict):
                    continue
                principal = str(item.get("principal") or "").strip()
                job = item.get("job")
                if not principal or not isinstance(job, dict):
                    continue
                enriched = self._with_routing(
                    job,
                    self._routing_for_run(db, str(job.get("run_id") or "")),
                )
                if self._upsert_job_row(
                    db, principal, enriched,
                    source_server_id=source,
                    source_event_id=f"reconcile:{source}",
                    reject_older=True,
                ):
                    applied += 1
        return applied

    def _apply_routing(
        self,
        db: sqlite3.Connection,
        routing: dict[str, Any],
    ) -> None:
        run_id = str(routing.get("run_id") or "").strip()
        origin = str(routing.get("origin_server_id") or "").strip()
        execution = str(routing.get("execution_server_id") or "").strip()
        if not run_id or not origin or not execution:
            return
        try:
            port = int(routing.get("execution_port") or 0)
        except (TypeError, ValueError):
            return
        values = {
            "run_id": run_id,
            "principal": str(routing.get("principal") or ""),
            "origin_server_id": origin,
            "execution_server_id": execution,
            "execution_port": port,
            "execution_branch": str(routing.get("execution_branch") or ""),
            "execution_revision": str(routing.get("execution_revision") or ""),
        }
        db.execute(
            """INSERT INTO run_routing(
                    run_id, principal, origin_server_id,
                    execution_server_id, execution_port,
                    execution_branch, execution_revision, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    principal=excluded.principal,
                    origin_server_id=excluded.origin_server_id,
                    execution_server_id=excluded.execution_server_id,
                    execution_port=excluded.execution_port,
                    execution_branch=excluded.execution_branch,
                    execution_revision=excluded.execution_revision,
                    updated_at=excluded.updated_at""",
            (
                values["run_id"], values["principal"], values["origin_server_id"],
                values["execution_server_id"], values["execution_port"],
                values["execution_branch"], values["execution_revision"],
                time.time(),
            ),
        )
        self._enrich_existing_run_jobs(db, run_id, values)

    def sync_cursor(self, source_server_id: str) -> int:
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT sequence FROM control_sync_cursors WHERE source_server_id=?",
                (str(source_server_id),),
            ).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def advance_sync_cursor(self, source_server_id: str, sequence: int) -> None:
        bounded = max(0, int(sequence))
        with self._lock, self._connection() as db:
            db.execute(
                """INSERT INTO control_sync_cursors(
                        source_server_id, sequence, updated_at
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(source_server_id) DO UPDATE SET
                        sequence=MAX(control_sync_cursors.sequence, excluded.sequence),
                        updated_at=excluded.updated_at""",
                (str(source_server_id), bounded, time.time()),
            )

    def list(self, principal: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT payload FROM jobs WHERE principal=?
                   ORDER BY updated_order DESC, updated_at DESC LIMIT ?""",
                (principal, max(1, min(limit, 2000))),
            ).fetchall()
        result = []
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def page(
        self, principal: str, *, page: int = 1, limit: int = 20,
    ) -> dict[str, Any]:
        return self.page_for_principals(
            [principal], page=page, limit=limit,
        )

    def page_for_principals(
        self, principals: Iterable[str], *, page: int = 1, limit: int = 20,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 100))
        requested_page = max(1, int(page))
        values = [str(item).strip() for item in principals if str(item).strip()]
        if not values:
            return {
                "jobs": [], "page": requested_page, "page_size": 0,
                "total": 0, "total_pages": 1, "has_more": False,
                "next_cursor": None,
            }
        placeholders = ",".join("?" for _ in values)
        start = (requested_page - 1) * bounded_limit
        with self._lock, self._connection() as db:
            total = int(db.execute(
                f"SELECT COUNT(DISTINCT job_id) FROM jobs WHERE principal IN ({placeholders})",
                values,
            ).fetchone()[0])
            rows = db.execute(
                f"""
                SELECT payload FROM (
                    SELECT payload, job_id, updated_at, updated_order, port,
                           ROW_NUMBER() OVER (
                               PARTITION BY job_id
                               ORDER BY updated_order DESC, updated_at DESC, port DESC
                           ) AS row_number
                    FROM jobs
                    WHERE principal IN ({placeholders})
                )
                WHERE row_number = 1
                ORDER BY updated_order DESC, updated_at DESC, job_id DESC
                LIMIT ? OFFSET ?
                """,
                [*values, bounded_limit, start],
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return {
            "jobs": result,
            "page": requested_page,
            "page_size": len(result),
            "total": total,
            "total_pages": max(1, (total + bounded_limit - 1) // bounded_limit),
            "has_more": start + len(result) < total,
            "next_cursor": None,
        }

    def list_all(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return the newest distinct jobs observed across principals.

        Manager may observe the same public job under its public projection
        and the submitting user's private projection.  De-duplicate by job
        ID so a stale public projection cannot hide a newer observed summary.
        """
        bounded = max(1, min(int(limit), 2000))
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT payload FROM jobs
                   ORDER BY updated_order DESC, updated_at DESC LIMIT ?""",
                (min(2000, max(bounded * 4, bounded)),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            job_id = str(value.get("job_id") or "").strip()
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            result.append(value)
            if len(result) >= bounded:
                break
        return result

    def ports_for(self, principal: str, job_id: str) -> list[int]:
        """Return cached origins for a known job, newest first.

        The index is routing metadata only; the service remains authoritative
        for the detail response.  A stopped cached port is still useful to
        try before falling back to the currently running services.
        """
        with self._lock, self._connection() as db:
            rows = db.execute(
                """SELECT port FROM jobs
                   WHERE principal=? AND job_id=?
                   ORDER BY updated_order DESC, updated_at DESC""",
                (principal, str(job_id)),
            ).fetchall()
        return [int(row["port"]) for row in rows]

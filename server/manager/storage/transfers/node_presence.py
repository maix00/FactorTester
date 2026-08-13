"""Authenticated, expiring local cache of node control-channel ownership."""

from __future__ import annotations

import json
import time
from pathlib import Path

from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import required
from server.manager.transfers.node_models import NodePresenceRecord


def _record(row, *, now: float) -> NodePresenceRecord:
    reachable = json.loads(str(row["reachable_from_json"]))
    if not isinstance(reachable, list):  # pragma: no cover - schema invariant
        raise RuntimeError("node reachability cache is invalid")
    return NodePresenceRecord(
        node_id=str(row["node_id"]),
        connection_owner_manager_id=str(row["connection_owner_manager_id"]),
        connection_id=str(row["connection_id"]),
        data_endpoint=str(row["data_endpoint"]),
        reachable_from=frozenset(str(item) for item in reachable),
        observed_at=float(row["observed_at"]),
        expires_at=float(row["expires_at"]),
        online=bool(row["online"]) and float(row["expires_at"]) > now,
    )


class NodePresenceStore(TransferDatabase):
    def __init__(self, path: str | Path, *, server_id: str) -> None:
        super().__init__(path, server_id=server_id)

    def observe(
        self,
        *,
        node_id: str,
        connection_owner_manager_id: str,
        connection_id: str,
        data_endpoint: str,
        reachable_from: tuple[str, ...] | frozenset[str],
        ttl: float,
        now: float | None = None,
    ) -> NodePresenceRecord:
        current = time.time() if now is None else float(now)
        expiry = current + max(5.0, min(300.0, float(ttl)))
        reachable_json = json.dumps(sorted({
            str(item).strip() for item in reachable_from if str(item).strip()
        }))
        values = (
            required(node_id, field="node_id"),
            required(
                connection_owner_manager_id,
                field="connection_owner_manager_id",
            ),
            required(connection_id, field="connection_id"),
            required(data_endpoint, field="data_endpoint"),
            reachable_json,
            current,
            expiry,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transfer_node_presence(
                    node_id, connection_owner_manager_id, connection_id,
                    data_endpoint, reachable_from_json, observed_at,
                    expires_at, online
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(node_id) DO UPDATE SET
                    connection_owner_manager_id=excluded.connection_owner_manager_id,
                    connection_id=excluded.connection_id,
                    data_endpoint=excluded.data_endpoint,
                    reachable_from_json=excluded.reachable_from_json,
                    observed_at=excluded.observed_at,
                    expires_at=excluded.expires_at,
                    online=1
                WHERE excluded.observed_at>=transfer_node_presence.observed_at
                """,
                values,
            )
            row = connection.execute(
                "SELECT * FROM transfer_node_presence WHERE node_id=?",
                (values[0],),
            ).fetchone()
        return _record(row, now=current)

    def get(
        self, node_id: str, *, now: float | None = None,
    ) -> NodePresenceRecord | None:
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM transfer_node_presence WHERE node_id=?",
                (required(node_id, field="node_id"),),
            ).fetchone()
        return _record(row, now=current) if row is not None else None

    def require_live(
        self, node_id: str, *, now: float | None = None,
    ) -> NodePresenceRecord:
        value = self.get(node_id, now=now)
        if value is None or not value.online:
            raise ConnectionError(f"node {node_id} is offline or stale")
        return value

    def mark_offline(
        self,
        *,
        node_id: str,
        connection_id: str,
        now: float | None = None,
    ) -> bool:
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE transfer_node_presence
                SET online=0, observed_at=?, expires_at=?
                WHERE node_id=? AND connection_id=?
                """,
                (
                    current, current,
                    required(node_id, field="node_id"),
                    required(connection_id, field="connection_id"),
                ),
            )
        return result.rowcount > 0


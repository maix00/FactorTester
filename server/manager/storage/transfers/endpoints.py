"""SQLite registry for public and FactorTester WireGuard node endpoints."""

from __future__ import annotations

import time
from pathlib import Path

from server.manager.network_endpoints import (
    ServerEndpoints,
    validate_server_endpoints,
)
from server.manager.storage.transfers.database import TransferDatabase
from server.manager.storage.transfers.records import required
from server.manager.transfers.planner import NodeEndpoint


class NodeEndpointStore(TransferDatabase):
    def advertise(
        self,
        node_id: str,
        endpoints: ServerEndpoints,
        *,
        ttl: float = 30.0,
        now: float | None = None,
    ) -> NodeEndpoint:
        current = time.time() if now is None else float(now)
        endpoints = validate_server_endpoints(endpoints)
        expiry = current + max(5.0, min(300.0, float(ttl)))
        identifier = required(node_id, field="node_id")
        values = (
            endpoints.client_control_endpoint,
            endpoints.client_data_endpoint,
            endpoints.peer_control_endpoint,
            endpoints.peer_data_endpoint,
        )
        if any(not str(value).strip() for value in values):
            raise ValueError("all node endpoints are required")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO transfer_node_endpoints(
                    node_id, client_control_endpoint, client_data_endpoint,
                    peer_control_endpoint, peer_data_endpoint, observed_at,
                    expires_at, online
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(node_id) DO UPDATE SET
                    client_control_endpoint=excluded.client_control_endpoint,
                    client_data_endpoint=excluded.client_data_endpoint,
                    peer_control_endpoint=excluded.peer_control_endpoint,
                    peer_data_endpoint=excluded.peer_data_endpoint,
                    observed_at=excluded.observed_at,
                    expires_at=excluded.expires_at,
                    online=1
                WHERE excluded.observed_at>=transfer_node_endpoints.observed_at
                """,
                (identifier, *values, current, expiry),
            )
        return self.require(identifier, now=current)

    def require(self, node_id: str, *, now: float | None = None) -> NodeEndpoint:
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM transfer_node_endpoints WHERE node_id=?",
                (required(node_id, field="node_id"),),
            ).fetchone()
        if row is None:
            raise KeyError("node endpoint is not registered")
        return _record(row, now=current)

    def snapshot(self, *, now: float | None = None) -> dict[str, NodeEndpoint]:
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM transfer_node_endpoints"
            ).fetchall()
        return {str(row["node_id"]): _record(row, now=current) for row in rows}


def _record(row, *, now: float) -> NodeEndpoint:
    expires_at = float(row["expires_at"])
    return NodeEndpoint(
        server_id=str(row["node_id"]),
        peer_data_endpoint=str(row["peer_data_endpoint"]),
        peer_control_endpoint=str(row["peer_control_endpoint"]),
        observed_at=float(row["observed_at"]),
        expires_at=expires_at,
        online=bool(row["online"]) and expires_at > now,
    )

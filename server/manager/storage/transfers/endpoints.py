"""SQLite registry for public and FactorTester WireGuard node endpoints."""

from __future__ import annotations

import sqlite3
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
    def next_advertisement_issued_at(
        self,
        node_id: str,
        *,
        requested: float,
    ) -> float:
        """Reserve a durable, strictly increasing local issuance time."""

        identifier = required(node_id, field="node_id")
        selected = float(requested)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT last_issued_at FROM transfer_node_advertisement_clock "
                "WHERE node_id=?",
                (identifier,),
            ).fetchone()
            if row is not None:
                selected = max(selected, float(row[0]) + 0.000001)
            connection.execute(
                """
                INSERT INTO transfer_node_advertisement_clock(
                    node_id, last_issued_at
                ) VALUES (?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    last_issued_at=excluded.last_issued_at
                """,
                (identifier, selected),
            )
        return selected

    def advertise(
        self,
        node_id: str,
        endpoints: ServerEndpoints,
        *,
        ttl: float = 30.0,
        now: float | None = None,
    ) -> NodeEndpoint:
        current = time.time() if now is None else float(now)
        expiry = current + max(5.0, min(300.0, float(ttl)))
        identifier, values = _validated_values(node_id, endpoints)
        with self._connect() as connection:
            _upsert_endpoint(
                connection,
                node_id=identifier,
                values=values,
                observed_at=current,
                expires_at=expiry,
            )
        return self.require(identifier, now=current)

    def accept_advertisement(
        self,
        node_id: str,
        endpoints: ServerEndpoints,
        *,
        nonce: str,
        issued_at: float,
        expires_at: float,
        now: float,
    ) -> NodeEndpoint:
        """Atomically reject replay and install a signed endpoint lease."""

        current = float(now)
        issued = float(issued_at)
        expiry = float(expires_at)
        if expiry <= current:
            raise PermissionError("transfer node advertisement expired")
        identifier, values = _validated_values(node_id, endpoints)
        selected_nonce = required(nonce, field="nonce")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM transfer_node_advertisement_nonces "
                    "WHERE expires_at<=?",
                    (current,),
                )
                previous = connection.execute(
                    "SELECT latest_issued_at, expires_at FROM "
                    "transfer_node_advertisement_state WHERE node_id=?",
                    (identifier,),
                ).fetchone()
                if (
                    previous is not None
                    and issued <= float(previous[0])
                ):
                    raise PermissionError(
                        "transfer node advertisement was stale or replayed"
                    )
                connection.execute(
                    """
                    INSERT INTO transfer_node_advertisement_nonces(
                        node_id, nonce, expires_at
                    ) VALUES (?, ?, ?)
                    """,
                    (identifier, selected_nonce, expiry),
                )
                connection.execute(
                    """
                    INSERT INTO transfer_node_advertisement_state(
                        node_id, latest_issued_at, latest_nonce, expires_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        latest_issued_at=excluded.latest_issued_at,
                        latest_nonce=excluded.latest_nonce,
                        expires_at=excluded.expires_at
                    """,
                    (identifier, issued, selected_nonce, expiry),
                )
                _upsert_endpoint(
                    connection,
                    node_id=identifier,
                    values=values,
                    observed_at=current,
                    expires_at=expiry,
                )
        except sqlite3.IntegrityError as exc:
            raise PermissionError(
                "transfer node advertisement was replayed"
            ) from exc
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


def _validated_values(
    node_id: str,
    endpoints: ServerEndpoints,
) -> tuple[str, tuple[str, str, str, str]]:
    selected = validate_server_endpoints(endpoints)
    identifier = required(node_id, field="node_id")
    values = (
        selected.client_control_endpoint,
        selected.client_data_endpoint,
        selected.peer_control_endpoint,
        selected.peer_data_endpoint,
    )
    if any(not str(value).strip() for value in values):
        raise ValueError("all node endpoints are required")
    return identifier, values


def _upsert_endpoint(
    connection,
    *,
    node_id: str,
    values: tuple[str, str, str, str],
    observed_at: float,
    expires_at: float,
) -> None:
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
        (node_id, *values, observed_at, expires_at),
    )

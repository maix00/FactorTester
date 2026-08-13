"""Composition root for Manager-local direct-transfer components."""

from __future__ import annotations

from server.manager.storage.transfers import (
    NodeEndpointStore,
    NodeIdentityRegistry,
    TransferAttemptStore,
    TransferReplicaStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.network_endpoints import (
    ServerEndpoints,
    endpoints_from_advertisement,
    validate_server_endpoints,
)
from server.manager.transfers.destination_tickets import DestinationTicketIssuer
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.origin_tickets import OriginTicketIssuer
from server.manager.transfers.security import NodeAuthenticator


class TransferStateMixin:
    def _init_transfer_state(self) -> None:
        self.transfer_database_path = self.state_root / "transfers.sqlite"
        self.node_identity_path = self.state_root / "node-identity.key"
        common = {
            "path": self.transfer_database_path,
            "server_id": self.server_id,
        }
        self.transfer_store = TransferStore(**common)
        self.transfer_attempts = TransferAttemptStore(**common)
        self.transfer_tickets = TransferTicketStore(**common)
        self.transfer_replicas = TransferReplicaStore(**common)
        self.transfer_endpoints = NodeEndpointStore(**common)
        self.node_identities = NodeIdentityRegistry(**common)
        self.node_key = NodeKey.load_or_create(
            self.node_identity_path,
            node_id=self.server_id,
        )
        self.node_identities.enroll(self.node_key.public_record())
        self.node_authenticator = NodeAuthenticator(self.node_identities)
        ticket_dependencies = {
            "manager_id": self.server_id,
            "replicas": self.transfer_replicas,
            "tickets": self.transfer_tickets,
        }
        self.origin_ticket_issuer = OriginTicketIssuer(**ticket_dependencies)
        self.destination_ticket_issuer = DestinationTicketIssuer(
            **ticket_dependencies,
        )

        self._transfer_server_endpoints: ServerEndpoints | None = None

    def configure_transfer_endpoints(
        self,
        endpoints: ServerEndpoints,
        *,
        ttl: float = 30.0,
        now: float | None = None,
    ):
        selected = validate_server_endpoints(endpoints)
        self._transfer_server_endpoints = selected
        return self.transfer_endpoints.advertise(
            self.server_id,
            selected,
            ttl=ttl,
            now=now,
        )

    def transfer_node_advertisement(
        self,
        *,
        ttl: float = 30.0,
        now: float | None = None,
    ) -> dict[str, object]:
        endpoints = self._transfer_server_endpoints
        if endpoints is None:
            raise RuntimeError("transfer endpoints are not configured")
        self.transfer_endpoints.advertise(
            self.server_id,
            endpoints,
            ttl=ttl,
            now=now,
        )
        return {
            "schema_version": 1,
            "node_id": self.server_id,
            "identity": self.node_key.public_record(),
            "client_control_endpoint": endpoints.client_control_endpoint,
            "client_data_endpoint": endpoints.client_data_endpoint,
            "peer_control_endpoint": endpoints.peer_control_endpoint,
            "peer_data_endpoint": endpoints.peer_data_endpoint,
            "lease_seconds": max(5.0, min(300.0, float(ttl))),
        }

    def accept_transfer_node_advertisement(
        self,
        value: dict[str, object],
        *,
        now: float | None = None,
    ):
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("unsupported transfer node advertisement")
        node_id = str(value.get("node_id") or "").strip()
        identity = value.get("identity")
        if not node_id or not isinstance(identity, dict):
            raise ValueError("transfer node identity is required")
        if str(identity.get("node_id") or "").strip() != node_id:
            raise ValueError("transfer node identity does not match advertisement")
        endpoints = endpoints_from_advertisement(value)
        try:
            ttl = float(value.get("lease_seconds") or 30.0)
        except (TypeError, ValueError) as exc:
            raise ValueError("transfer node lease is invalid") from exc
        self.node_identities.enroll(identity)
        return self.transfer_endpoints.advertise(
            node_id,
            endpoints,
            ttl=ttl,
            now=now,
        )

    def stop_node_agent(self) -> None:
        """Compatibility lifecycle hook; direct peers need no background agent."""

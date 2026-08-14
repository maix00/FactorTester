"""Composition root for Manager-local direct-transfer components."""

from __future__ import annotations

import secrets
import time

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
from server.manager.transfers.node_advertisements import (
    ADVERTISEMENT_SCHEMA_VERSION,
    normalized_lease,
    signed_advertisement,
    verify_advertisement,
)
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
        requested = time.time() if now is None else float(now)
        current = self.transfer_endpoints.next_advertisement_issued_at(
            self.server_id,
            requested=requested,
        )
        lease = normalized_lease(ttl)
        self.transfer_endpoints.advertise(
            self.server_id,
            endpoints,
            ttl=lease,
            now=current,
        )
        return signed_advertisement({
            "schema_version": ADVERTISEMENT_SCHEMA_VERSION,
            "node_id": self.server_id,
            "identity": self.node_key.public_record(),
            "client_control_endpoint": endpoints.client_control_endpoint,
            "client_data_endpoint": endpoints.client_data_endpoint,
            "peer_control_endpoint": endpoints.peer_control_endpoint,
            "peer_data_endpoint": endpoints.peer_data_endpoint,
            "issued_at": current,
            "lease_seconds": lease,
            "nonce": secrets.token_urlsafe(24),
        }, node_key=self.node_key)

    def accept_transfer_node_advertisement(
        self,
        value: dict[str, object],
        *,
        now: float | None = None,
    ):
        current = time.time() if now is None else float(now)
        verified, endpoints = self.validate_transfer_node_advertisement(
            value,
            now=current,
        )
        return self.install_transfer_node_advertisement(
            verified,
            endpoints,
            now=current,
        )

    def validate_transfer_node_advertisement(
        self,
        value: dict[str, object],
        *,
        expected_node_id: str = "",
        now: float | None = None,
    ):
        """Validate a signed advertisement without changing local state."""
        current = time.time() if now is None else float(now)
        verified = verify_advertisement(value, now=current)
        expected = str(expected_node_id or "").strip()
        if expected and verified.node_id != expected:
            raise ValueError(
                "federation server_id does not match signed node_id"
            )
        endpoints = endpoints_from_advertisement(value)
        try:
            enrolled = self.node_identities.require(verified.node_id)
        except KeyError:
            enrolled = None
        if (
            enrolled is not None
            and enrolled.fingerprint != verified.identity["fingerprint"]
        ):
            raise ValueError("node key change requires explicit rotation")
        return verified, endpoints

    def install_transfer_node_advertisement(
        self,
        verified,
        endpoints: ServerEndpoints,
        *,
        now: float,
    ):
        """Install one already verified direct-node identity and endpoint."""
        current = float(now)
        self.node_identities.enroll(verified.identity, now=current)
        return self.transfer_endpoints.accept_advertisement(
            verified.node_id,
            endpoints,
            nonce=verified.nonce,
            issued_at=verified.issued_at,
            expires_at=verified.expires_at,
            now=current,
        )

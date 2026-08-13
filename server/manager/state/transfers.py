"""Composition root for Manager-local federated transfer components."""

from __future__ import annotations

from server.manager.storage.transfers import (
    NodeCommandQueue,
    NodeIdentityRegistry,
    NodePresenceStore,
    TransferAttemptStore,
    TransferInboxStore,
    TransferStore,
    TransferTicketStore,
    TransferReplicaStore,
)
from server.manager.transfers.node_hub import NodeControlHub
from server.manager.transfers.node_agent import NodeAgent
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.security import NodeAuthenticator
from server.manager.transfers.origin_tickets import OriginTicketIssuer
from server.manager.transfers.producer_tickets import ProducerTicketIssuer


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
        self.transfer_inbox = TransferInboxStore(**common)
        self.transfer_tickets = TransferTicketStore(**common)
        self.transfer_replicas = TransferReplicaStore(**common)
        self.node_identities = NodeIdentityRegistry(**common)
        self.node_commands = NodeCommandQueue(**common)
        self.node_presence = NodePresenceStore(**common)
        self.node_key = NodeKey.load_or_create(
            self.node_identity_path,
            node_id=self.server_id,
        )
        self.node_identities.enroll(self.node_key.public_record())
        self.node_authenticator = NodeAuthenticator(self.node_identities)
        self.node_control_hub = NodeControlHub(
            self.node_commands,
            self.node_presence,
            manager_id=self.server_id,
        )
        self.origin_ticket_issuer = OriginTicketIssuer(
            manager_id=self.server_id,
            replicas=self.transfer_replicas,
            tickets=self.transfer_tickets,
        )
        self.producer_ticket_issuer = ProducerTicketIssuer(
            manager_id=self.server_id,
            requests=self.transfer_store,
            attempts=self.transfer_attempts,
            tickets=self.transfer_tickets,
        )
        self.node_agent: NodeAgent | None = None

    def start_node_agent(
        self,
        *,
        manager_endpoint: str,
        enrollment_token: str,
    ) -> None:
        endpoint = str(manager_endpoint or "").strip().rstrip("/")
        if endpoint.endswith("/api/federation/register"):
            endpoint = endpoint.removesuffix("/api/federation/register")
        if not endpoint:
            raise ValueError("node control Manager endpoint is required")
        self.stop_node_agent()
        self.node_agent = NodeAgent(
            inbox=self.transfer_inbox,
            key=self.node_key,
            manager_endpoints=lambda: (endpoint,),
            enrollment_token=enrollment_token,
            data_endpoint="http://127.0.0.1:7997",
            reachable_from=(self.server_id,),
        )
        self.node_agent.start()

    def stop_node_agent(self) -> None:
        agent = self.node_agent
        self.node_agent = None
        if agent is not None:
            agent.stop()

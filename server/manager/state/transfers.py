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
)
from server.manager.transfers.node_hub import NodeControlHub
from server.manager.transfers.node_keys import NodeKey
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
        self.transfer_inbox = TransferInboxStore(**common)
        self.transfer_tickets = TransferTicketStore(**common)
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

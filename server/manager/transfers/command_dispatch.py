"""Route one fixed transfer command to its control-connection owner."""

from __future__ import annotations

from server.manager.transfers.models import TransferAttemptRecord, TransferMode
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_hub import NodeControlHub
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.node_models import NewNodeCommand
from server.manager.transfers.wire import transfer_context_payload


class TransferCommandDispatcher:
    def __init__(
        self,
        *,
        manager_id: str,
        key: NodeKey,
        enrollment_token: str,
        local_hub: NodeControlHub,
    ) -> None:
        self.manager_id = str(manager_id or "").strip()
        self.key = key
        self.enrollment_token = str(enrollment_token or "").strip()
        self.local_hub = local_hub
        self._clients: dict[str, NodeControlClient] = {}

    def dispatch(self, transfer, attempt: TransferAttemptRecord):
        command_type, target = _command_target(attempt)
        payload = {
            "schema_version": 1,
            "context": transfer_context_payload(transfer, attempt),
        }
        value = NewNodeCommand(
            idempotency_key=f"{attempt.attempt_id}:{command_type}",
            transfer_id=transfer.transfer_id,
            attempt_id=attempt.attempt_id,
            command_type=command_type,
            target_server_id=target,
            payload=payload,
            expires_at=min(transfer.expires_at, attempt.expires_at),
        )
        if attempt.connection_owner_manager_id == self.manager_id:
            return self.local_hub.enqueue(value)
        endpoint = attempt.connection_owner_control_endpoint.rstrip("/")
        if not endpoint:
            raise ConnectionError("connection-owner Manager endpoint is missing")
        client = self._clients.get(endpoint)
        if client is None:
            client = NodeControlClient(
                endpoint,
                key=self.key,
                enrollment_token=self.enrollment_token,
            )
            self._clients[endpoint] = client
        client.enroll()
        return client.signed_json(
            "/api/federation/transfers/commands",
            {
                "schema_version": 1,
                "command": {
                    "idempotency_key": value.idempotency_key,
                    "command_type": value.command_type,
                    "target_server_id": value.target_server_id,
                    "expires_at": value.expires_at,
                },
                "context": payload["context"],
            },
        )


def _command_target(attempt: TransferAttemptRecord) -> tuple[str, str]:
    if attempt.mode is TransferMode.SOURCE_PUSH:
        return "source.push", attempt.source_server_id
    if attempt.mode is TransferMode.DESTINATION_PULL:
        return "destination.pull", attempt.destination_server_id
    raise ValueError(f"Attempt mode {attempt.mode.value} needs no node command")

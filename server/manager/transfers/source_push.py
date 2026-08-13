"""Execute a source-initiated stream from local storage to relay 7997."""

from __future__ import annotations

from pathlib import Path
from urllib.request import Request

from server.manager.data_plane.integrity import verify_file
from server.manager.domain.federation_transport import FederationTransport
from server.manager.storage.transfers import TransferReplicaStore
from server.manager.transfers.models import TransferCommandRecord, TransferMode
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.wire import parse_transfer_context


class SourcePushExecutor:
    def __init__(
        self,
        *,
        server_id: str,
        replicas: TransferReplicaStore,
        key: NodeKey,
        enrollment_token: str,
        origin_resolver,
        transport: FederationTransport | None = None,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        self.replicas = replicas
        self.key = key
        self.enrollment_token = str(enrollment_token or "").strip()
        self.origin_resolver = origin_resolver
        self.transport = transport or FederationTransport()
        self._clients: dict[str, NodeControlClient] = {}

    def execute(self, command: TransferCommandRecord) -> int:
        if command.command_type != "source.push":
            raise ValueError("source push executor received another command type")
        raw_context = command.payload.get("context")
        if not isinstance(raw_context, dict):
            raise ValueError("source push command has no transfer context")
        transfer, attempt = parse_transfer_context(raw_context)
        if transfer.transfer_id != command.transfer_id:
            raise ValueError("source push transfer ID does not match command")
        if attempt.attempt_id != command.attempt_id:
            raise ValueError("source push Attempt ID does not match command")
        if attempt.mode is not TransferMode.SOURCE_PUSH:
            raise ValueError("source push command has another Attempt mode")
        if attempt.source_server_id != self.server_id:
            raise PermissionError("source push command targets another source")
        self.replicas.import_context(transfer, attempt)
        source = Path(self.origin_resolver(transfer)).expanduser().resolve()
        verify_file(
            source,
            expected_size=attempt.expected_size,
            expected_sha256=attempt.expected_sha256,
        )
        access = self._producer_access(attempt)
        return self._upload(source, attempt, access)

    def _producer_access(self, attempt) -> dict[str, object]:
        endpoint = attempt.request_owner_control_endpoint.rstrip("/")
        if not endpoint:
            raise ConnectionError("request-owner Manager endpoint is missing")
        client = self._clients.get(endpoint)
        if client is None:
            client = NodeControlClient(
                endpoint,
                key=self.key,
                enrollment_token=self.enrollment_token,
                transport=self.transport,
            )
            self._clients[endpoint] = client
        client.enroll()
        return client.signed_json(
            "/api/federation/transfers/producer-ticket",
            {"attempt_id": attempt.attempt_id},
        )

    def _upload(self, source: Path, attempt, access: dict[str, object]) -> int:
        bearer = str(access.get("bearer") or "").strip()
        data_endpoint = str(access.get("data_endpoint") or "").rstrip("/")
        path = str(access.get("path") or "").strip()
        if not bearer or not data_endpoint or not path.startswith("/"):
            raise ConnectionError("producer capability response is incomplete")
        remaining = attempt.expected_size - attempt.resume_offset
        with source.open("rb") as stream:
            stream.seek(attempt.resume_offset)
            request = Request(
                data_endpoint + path,
                data=stream,
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "Content-Length": str(remaining),
                    "Content-Type": "application/octet-stream",
                    "X-FactorTester-Node-ID": self.server_id,
                },
                method="PUT",
            )
            with self.transport.open(request, timeout=120.0) as response:
                if response.status != 204:
                    raise ConnectionError(
                        f"relay producer returned HTTP {response.status}"
                    )
        return remaining

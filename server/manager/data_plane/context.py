"""Runtime dependencies and local path policy for the sole 7997 process."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from server.manager.domain.federation_transport import FederationTransport
from server.manager.data_plane.integrity import verify_file
from server.manager.data_plane.lifecycle import TransferLifecycle
from server.manager.data_plane.staging import destination_path, resume_offset
from server.manager.storage.transfers import (
    TransferAttemptStore,
    TransferStore,
    TransferTicketStore,
)
from server.manager.transfers.models import TransferAttemptRecord, TransferRecord


@dataclass(frozen=True, slots=True)
class TransferContext:
    transfer: TransferRecord
    attempt: TransferAttemptRecord


class DataPlaneRuntime:
    def __init__(
        self,
        *,
        server_id: str,
        transfer_database: str | Path,
        staging_root: str | Path,
        origin_resolver: Callable[[TransferRecord], Path],
        origin_ticket_provider: Callable[[TransferContext], str] | None = None,
        source_endpoint_provider: Callable[[TransferContext], str] | None = None,
        destination_ticket_provider: (
            Callable[[TransferContext], str] | None
        ) = None,
        destination_endpoint_provider: (
            Callable[[TransferContext], str] | None
        ) = None,
        allowed_origins: tuple[str, ...] = (),
        transport: FederationTransport | None = None,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        if not self.server_id:
            raise ValueError("data-plane server_id is required")
        path = Path(transfer_database).expanduser().resolve()
        self.requests = TransferStore(path, server_id=self.server_id)
        self.attempts = TransferAttemptStore(path, server_id=self.server_id)
        self.tickets = TransferTicketStore(path, server_id=self.server_id)
        self.lifecycle = TransferLifecycle(
            requests=self.requests,
            attempts=self.attempts,
        )
        self.staging_root = Path(staging_root).expanduser().resolve()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.origin_resolver = origin_resolver
        self.origin_ticket_provider = origin_ticket_provider
        self.source_endpoint_provider = source_endpoint_provider
        self.destination_ticket_provider = destination_ticket_provider
        self.destination_endpoint_provider = destination_endpoint_provider
        self.allowed_origins = frozenset(
            str(value or "").strip().rstrip("/")
            for value in allowed_origins
            if str(value or "").strip()
        )
        self.transport = transport or FederationTransport()

    def context(self, attempt_id: str) -> TransferContext:
        attempt = self.attempts.require(attempt_id)
        transfer = self.requests.require(attempt.transfer_id)
        return TransferContext(transfer=transfer, attempt=attempt)

    def origin_path(self, context: TransferContext) -> Path:
        path = self.origin_resolver(context.transfer).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("transfer origin file is unavailable")
        verify_file(
            path,
            expected_size=context.attempt.expected_size,
            expected_sha256=context.attempt.expected_sha256,
        )
        return path

    def destination_path(
        self,
        transfer: TransferRecord,
        attempt: TransferAttemptRecord,
    ) -> Path:
        del attempt
        return destination_path(self.staging_root, transfer)

    def resume_offset(self, transfer: TransferRecord) -> int:
        return resume_offset(self.staging_root, transfer)

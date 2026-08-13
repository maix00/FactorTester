"""Runtime dependencies and local path policy for the sole 7997 process."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from server.manager.data_plane.relay import RelayRegistry
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
        relay_buffer_bytes: int = 4 * 1024 * 1024,
        relay_timeout: float = 30.0,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        if not self.server_id:
            raise ValueError("data-plane server_id is required")
        path = Path(transfer_database).expanduser().resolve()
        self.requests = TransferStore(path, server_id=self.server_id)
        self.attempts = TransferAttemptStore(path, server_id=self.server_id)
        self.tickets = TransferTicketStore(path, server_id=self.server_id)
        self.staging_root = Path(staging_root).expanduser().resolve()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.origin_resolver = origin_resolver
        self.relays = RelayRegistry(
            max_buffer_bytes=relay_buffer_bytes,
            rendezvous_timeout=relay_timeout,
        )

    def context(self, attempt_id: str) -> TransferContext:
        attempt = self.attempts.require(attempt_id)
        transfer = self.requests.require(attempt.transfer_id)
        return TransferContext(transfer=transfer, attempt=attempt)

    def origin_path(self, context: TransferContext) -> Path:
        path = self.origin_resolver(context.transfer).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("transfer origin file is unavailable")
        return path

    def destination_path(
        self,
        transfer: TransferRecord,
        attempt: TransferAttemptRecord,
    ) -> Path:
        name = _safe_component(
            transfer.artifact_name or f"{transfer.transfer_id}.bin"
        )
        return (
            self.staging_root
            / _safe_component(transfer.principal)
            / transfer.transfer_id
            / f"{attempt.ordinal}-{name}"
        ).resolve()


def _safe_component(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip(".-")
    if not result:
        raise ValueError("transfer path component is empty")
    return result[:128]

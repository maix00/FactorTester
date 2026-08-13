"""Request and response values at the transfer-coordinator boundary."""

from __future__ import annotations

from dataclasses import dataclass

from server.manager.transfers.models import TransferMode


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    idempotency_key: str
    principal: str
    storage_server_id: str
    job_id: str
    artifact_name: str
    expected_size: int
    expected_sha256: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class TransferAccess:
    transfer_id: str
    attempt_id: str
    mode: TransferMode
    data_endpoint: str
    path: str
    bearer: str
    expires_at: float


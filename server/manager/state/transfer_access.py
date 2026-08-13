"""Manager-local orchestration boundary for client transfer capabilities."""

from __future__ import annotations

import time
from collections.abc import Mapping

from server.manager.transfers.coordinator import DownloadRequest, TransferCoordinator
from server.manager.transfers.coordinator import UploadRequest
from server.manager.data_plane.staging import resume_offset, storage_reference
from server.manager.transfers.peer_gateway import TransferPeerGateway


class TransferAccessStateMixin:
    def _init_transfer_access(self) -> None:
        self.transfer_peer_gateway = TransferPeerGateway(key=self.node_key)
        self.transfer_coordinator: TransferCoordinator | None = None

    def configure_transfer_access(self, client_data_endpoint: str) -> None:
        self.transfer_coordinator = TransferCoordinator(
            manager_id=self.server_id,
            client_data_endpoint=client_data_endpoint,
            requests=self.transfer_store,
            attempts=self.transfer_attempts,
            tickets=self.transfer_tickets,
            peer_gateway=self.transfer_peer_gateway,
            local_resume_offset_provider=lambda transfer, _attempt: resume_offset(
                self.transfer_submission_root, transfer,
            ),
        )

    def prepare_artifact_download(
        self,
        *,
        principal: str,
        storage_server_id: str,
        job_id: str,
        artifact: Mapping[str, object],
        idempotency_key: str,
        now: float | None = None,
        ttl: float = 15 * 60,
    ) -> dict[str, object]:
        coordinator = self.transfer_coordinator
        if coordinator is None:
            raise RuntimeError("transfer access is not configured")
        current = time.time() if now is None else float(now)
        expiry = current + max(30.0, min(3600.0, float(ttl)))
        access = coordinator.prepare_download(
            DownloadRequest(
                idempotency_key=str(idempotency_key or "").strip(),
                principal=str(principal or "").strip(),
                storage_server_id=str(storage_server_id or "").strip(),
                job_id=str(job_id or "").strip(),
                artifact_name=str(artifact.get("name") or "").strip(),
                expected_size=int(artifact.get("size_bytes") or 0),
                expected_sha256=str(
                    artifact.get("content_hash") or ""
                ).strip().lower(),
                expires_at=expiry,
            ),
            endpoints=self.transfer_endpoints.snapshot(now=current),
            now=current,
            ticket_ttl=ttl,
        )
        return {
            "transfer_id": access.transfer_id,
            "attempt_id": access.attempt_id,
            "mode": access.mode.value,
            "data_endpoint": access.data_endpoint,
            "path": access.path,
            "url": access.data_endpoint.rstrip("/") + access.path,
            "bearer": access.bearer,
            "expires_at": access.expires_at,
            "resume_offset": access.resume_offset,
            "expected_size": access.expected_size,
        }

    def prepare_submission_upload(
        self,
        *,
        principal: str,
        storage_server_id: str,
        job_id: str,
        name: str,
        expected_size: int,
        expected_sha256: str,
        idempotency_key: str,
        now: float | None = None,
        ttl: float = 15 * 60,
    ) -> dict[str, object]:
        coordinator = self.transfer_coordinator
        if coordinator is None:
            raise RuntimeError("transfer access is not configured")
        current = time.time() if now is None else float(now)
        expiry = current + max(30.0, min(3600.0, float(ttl)))
        access = coordinator.prepare_upload(
            UploadRequest(
                idempotency_key=str(idempotency_key or "").strip(),
                principal=str(principal or "").strip(),
                storage_server_id=str(storage_server_id or "").strip(),
                job_id=str(job_id or "").strip(),
                artifact_name=str(name or "").strip(),
                expected_size=int(expected_size),
                expected_sha256=str(expected_sha256 or "").strip().lower(),
                expires_at=expiry,
            ),
            endpoints=self.transfer_endpoints.snapshot(now=current),
            now=current,
            ticket_ttl=ttl,
        )
        return {
            "transfer_id": access.transfer_id,
            "attempt_id": access.attempt_id,
            "mode": access.mode.value,
            "data_endpoint": access.data_endpoint,
            "path": access.path,
            "url": access.data_endpoint.rstrip("/") + access.path,
            "bearer": access.bearer,
            "expires_at": access.expires_at,
            "resume_offset": access.resume_offset,
            "expected_size": access.expected_size,
        }

    def transfer_access_status(
        self, transfer_id: str, *, principal: str,
    ) -> dict[str, object]:
        transfer = self.transfer_store.require(transfer_id)
        if transfer.principal != str(principal or "").strip():
            raise KeyError("transfer was not found")
        attempt = self.transfer_attempts.latest(transfer.transfer_id)
        return {
            "transfer_id": transfer.transfer_id,
            "operation": transfer.operation.value,
            "status": transfer.status.value,
            "attempt_id": attempt.attempt_id if attempt is not None else "",
            "attempt_status": (
                attempt.status.value if attempt is not None else ""
            ),
            "resume_offset": (
                attempt.resume_offset if attempt is not None else 0
            ),
            "expected_size": transfer.expected_size,
            "storage_reference": (
                storage_reference(transfer)
                if transfer.status.value == "completed"
                else ""
            ),
        }


__all__ = ["TransferAccessStateMixin"]

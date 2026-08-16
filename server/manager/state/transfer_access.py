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
        return self.prepare_object_download(
            principal=principal,
            storage_server_id=storage_server_id,
            object_kind="job_artifact",
            object_id=f"{job_id}:{str(artifact.get('name') or '').strip()}",
            expected_size=int(artifact.get("size_bytes") or 0),
            expected_sha256=str(
                artifact.get("content_hash") or ""
            ).strip().lower(),
            idempotency_key=idempotency_key,
            job_id=job_id,
            artifact_name=str(artifact.get("name") or "").strip(),
            now=now,
            ttl=ttl,
        )

    def prepare_object_download(
        self,
        *,
        principal: str,
        storage_server_id: str,
        object_kind: str,
        object_id: str,
        expected_size: int,
        expected_sha256: str,
        idempotency_key: str,
        job_id: str = "",
        artifact_name: str = "",
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
                artifact_name=str(artifact_name or "").strip(),
                expected_size=int(expected_size),
                expected_sha256=str(expected_sha256 or "").strip().lower(),
                expires_at=expiry,
                object_kind=str(object_kind or "").strip(),
                object_id=str(object_id or "").strip(),
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
                object_kind="job_submission",
                object_id=f"{job_id}:{str(name or '').strip()}",
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

    def prepare_object_upload(
        self,
        *,
        principal: str,
        storage_server_id: str,
        object_kind: str,
        object_id: str,
        filename: str,
        expected_size: int,
        expected_sha256: str,
        idempotency_key: str,
        content_type: str = "application/octet-stream",
        now: float | None = None,
        ttl: float = 15 * 60,
    ) -> dict[str, object]:
        """Prepare a generic object upload while retaining Job compatibility."""
        coordinator = self.transfer_coordinator
        if coordinator is None:
            raise RuntimeError("transfer access is not configured")
        current = time.time() if now is None else float(now)
        expiry = current + max(30.0, min(3600.0, float(ttl)))
        safe_name = str(filename or "").strip()
        access = coordinator.prepare_upload(
            UploadRequest(
                idempotency_key=str(idempotency_key or "").strip(),
                principal=str(principal or "").strip(),
                storage_server_id=str(storage_server_id or "").strip(),
                job_id="",
                artifact_name=safe_name,
                expected_size=int(expected_size),
                expected_sha256=str(expected_sha256 or "").strip().lower(),
                expires_at=expiry,
                object_kind=str(object_kind or "").strip(),
                object_id=str(object_id or "").strip(),
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
            "filename": safe_name,
            "content_type": str(content_type or "application/octet-stream"),
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

    def require_completed_submission_upload(
        self,
        transfer_id: str,
        *,
        principal: str,
        job_id: str,
        artifact_name: str,
        expected_size: int,
        expected_sha256: str,
    ) -> dict[str, object]:
        """Validate one completed 7997 upload before promoting its metadata.

        A transfer id is a bearer-like value.  Completion callers must not be
        able to reuse a different completed upload belonging to the same
        account to mark an arbitrary local artifact as remotely available.
        """
        transfer = self.transfer_store.require(str(transfer_id or "").strip())
        if (
            transfer.principal != str(principal or "").strip()
            or transfer.operation.value != "upload"
            or transfer.object_kind != "job_submission"
            or transfer.job_id != str(job_id or "").strip()
            or transfer.artifact_name != str(artifact_name or "").strip()
            or transfer.expected_size != int(expected_size)
            or transfer.expected_sha256 != str(expected_sha256 or "").strip().lower()
        ):
            raise KeyError("transfer was not found")
        status = self.transfer_access_status(
            transfer.transfer_id, principal=principal,
        )
        if status.get("status") != "completed":
            raise RuntimeError("local artifact upload is not complete")
        return status


__all__ = ["TransferAccessStateMixin"]

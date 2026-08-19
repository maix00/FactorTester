"""Stage factor-source objects on a selected execution Manager."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from server.manager.objects.models import TransferObjectKind
from server.manager.services.data_plane_client import loopback_client_access
from server.manager.transfers.models import TransferStatus


class FactorSourceTransfer:
    """Use the existing local 7997 upload route for remote Run inputs."""

    def __init__(self, state: object) -> None:
        self.state = state

    def stage(
        self,
        entries: Iterable[dict[str, object]],
        *,
        principal: str,
        target_server_id: str,
    ) -> None:
        target = str(target_server_id or "").strip()
        if not target or target == str(self.state.server_id or "").strip():
            return
        for entry in entries:
            self._stage_one(
                entry,
                principal=principal,
                target_server_id=target,
            )

    def _stage_one(
        self,
        entry: dict[str, object],
        *,
        principal: str,
        target_server_id: str,
    ) -> None:
        object_id = str(
            entry.get("canonical_family_ref")
            or entry.get("object_id")
            or ""
        ).strip()
        source = entry.get("source_code")
        if not object_id or not isinstance(source, str) or not source.strip():
            raise ValueError("factor source object is not available at origin")
        raw = source.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        declared_hash = str(entry.get("source_sha256") or "").strip().lower()
        declared_size = int(entry.get("source_bytes") or -1)
        if digest != declared_hash or len(raw) != declared_size:
            raise ValueError("factor source object changed before transfer")
        idempotency_key = f"factor-source:{target_server_id}:{object_id}:{digest}"
        coordinator = getattr(self.state, "transfer_coordinator", None)
        requests = getattr(coordinator, "requests", None)
        existing = (
            requests.by_idempotency_key(idempotency_key)
            if requests is not None and hasattr(requests, "by_idempotency_key")
            else None
        )
        if existing is not None and existing.status is TransferStatus.COMPLETED:
            return
        access = self.state.prepare_object_upload(
            principal=str(principal or "").strip(),
            storage_server_id=target_server_id,
            object_kind=TransferObjectKind.FACTOR_SOURCE.value,
            object_id=object_id,
            filename=f"{object_id.rsplit(':', 1)[-1]}.py",
            expected_size=len(raw),
            expected_sha256=digest,
            idempotency_key=idempotency_key,
            content_type="text/x-python",
        )
        upload_url, tls_context = loopback_client_access(access.get("url"))
        request = Request(
            upload_url,
            data=raw,
            headers={
                "Authorization": f"Bearer {access.get('bearer') or ''}",
                "Content-Type": "text/x-python",
                "Content-Length": str(len(raw)),
            },
            method="PUT",
        )
        try:
            with urlopen(
                request, timeout=120.0, context=tls_context,
            ) as response:
                if not 200 <= int(response.status) < 300:
                    raise ConnectionError(
                        f"factor source destination returned HTTP {response.status}"
                    )
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise ConnectionError(
                f"factor source destination {target_server_id} is unavailable"
            ) from exc


__all__ = ["FactorSourceTransfer"]

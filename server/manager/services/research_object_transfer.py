"""7997 client for lazy research-object reads."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from server.manager.objects import research_object_id
from server.manager.services.data_plane_client import loopback_client_access


class ResearchObjectTransfer:
    """Bridge metadata tickets to the byte data plane without base64."""

    def __init__(
        self,
        *,
        metadata_reader: Callable[..., dict[str, object]],
        access_provider: Callable[..., dict[str, object]] | None,
        server_id: str,
        source_server_reader: Callable[[str], str] | None = None,
    ) -> None:
        self.metadata_reader = metadata_reader
        self.access_provider = access_provider
        self.server_id = str(server_id or "").strip()
        self.source_server_reader = source_server_reader

    def read(
        self,
        publication_id: str,
        viewer_ref: str | None,
        *,
        object_kind: str,
        item_id: str,
    ) -> tuple[bytes, str, str]:
        response = self.metadata_reader(
            publication_id,
            viewer_ref,
            operation="object-metadata",
            payload={"args": [item_id], "object_kind": object_kind},
        )
        metadata = response.get("value")
        if not isinstance(metadata, dict) or metadata.get("kind") != "object":
            raise ValueError("federated research object metadata is invalid")
        if self.access_provider is None:
            raise RuntimeError("research object transfer is not configured")
        source_server_id = str(metadata.get("storage_server_id") or "").strip()
        if not source_server_id and self.source_server_reader is not None:
            source_server_id = str(
                self.source_server_reader(publication_id) or ""
            ).strip()
        source_server_id = source_server_id or self.server_id
        expected_size = int(metadata.get("size_bytes") or 0)
        expected_sha256 = str(metadata.get("content_hash") or "").strip().lower()
        object_id = research_object_id(publication_id, item_id)
        access = self.access_provider(
            principal=str(viewer_ref or "__public_jobs__"),
            storage_server_id=source_server_id,
            object_kind=object_kind,
            object_id=object_id,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            idempotency_key=(
                f"research-object:{object_kind}:{object_id}:{expected_sha256}"
            ),
        )
        local_url, tls_context = loopback_client_access(access.get("url"))
        request = Request(
            local_url,
            headers={"Authorization": f"Bearer {access.get('bearer') or ''}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=120.0, context=tls_context) as response_stream:
                raw = response_stream.read(expected_size + 1)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise ConnectionError(
                "research object data source is unavailable"
            ) from exc
        if len(raw) != expected_size:
            raise ValueError("research object size is invalid")
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("research object hash is invalid")
        return (
            raw,
            str(metadata.get("content_type") or "application/octet-stream"),
            str(metadata.get("filename") or item_id),
        )


__all__ = ["ResearchObjectTransfer"]

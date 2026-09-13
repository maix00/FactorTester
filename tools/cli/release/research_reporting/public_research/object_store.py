"""Object-level read Adapter for a persisted research publication."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mimetypes
import os
import secrets
import shutil
from pathlib import Path
from typing import Any

from .library import _attachment_id


@dataclass(frozen=True, slots=True)
class PublicResearchObject:
    path: Path
    size_bytes: int
    content_hash: str
    content_type: str
    filename: str


class PublicResearchObjectStore:
    """Keep publication permission and file identity at the research seam."""

    def __init__(self, library: object) -> None:
        self.library = library

    def resolve(
        self,
        publication_id: str,
        object_kind: str,
        item_id: str,
        viewer_ref: str | None,
    ) -> PublicResearchObject:
        record = self.library._record(publication_id)
        if not self.library.can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        projection = self.library._projection(publication_id)
        metadata, path = self._entry(projection, publication_id, object_kind, item_id)
        self.library.require_resource_access(record, metadata, viewer_ref)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError("research object is unavailable")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        expected = str(metadata.get("content_hash") or digest).lower()
        if expected != digest:
            raise ValueError("research object integrity check failed")
        media_type = str(metadata.get("media_type") or "").strip()
        filename = str(metadata.get("filename") or path.name).strip() or path.name
        return PublicResearchObject(
            path=path,
            size_bytes=len(raw),
            content_hash=digest,
            content_type=media_type or mimetypes.guess_type(filename)[0]
            or "application/octet-stream",
            filename=filename,
        )

    def metadata(
        self,
        publication_id: str,
        object_kind: str,
        item_id: str,
        viewer_ref: str | None,
    ) -> dict[str, Any]:
        value = self.resolve(
            publication_id, object_kind, item_id, viewer_ref,
        )
        return {
            "kind": "object",
            "object_kind": object_kind,
            "object_id": item_id,
            "size_bytes": value.size_bytes,
            "content_hash": value.content_hash,
            "content_type": value.content_type,
            "filename": value.filename,
            "storage_server_id": str(
                self.library.storage_server_id or ""
            ),
        }

    def descriptor(
        self,
        publication_id: str,
        object_kind: str,
        item_id: str,
        viewer_ref: str | None,
    ) -> dict[str, Any]:
        """Return declared object metadata without requiring stored bytes.

        Publication control metadata is allowed to arrive before its 7997
        body.  Upload-ticket issuance therefore cannot call ``resolve``;
        this descriptor seam validates ownership and the immutable digest
        while accepting a not-yet-materialized destination.
        """
        record = self.library._record(publication_id)
        if not self.library.can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        projection = self.library._projection(publication_id)
        metadata, _path = self._entry(
            projection, publication_id, object_kind, item_id,
        )
        self.library.require_resource_access(record, metadata, viewer_ref)
        digest = str(metadata.get("content_hash") or "").strip().lower()
        if len(digest) != 64:
            raise ValueError("research object metadata has no content hash")
        size = metadata.get("size_bytes", metadata.get("size"))
        return {
            "object_kind": object_kind,
            "object_id": item_id,
            "size_bytes": int(size) if size is not None else None,
            "content_hash": digest,
            "content_type": str(
                metadata.get("media_type") or "application/octet-stream"
            ),
            "filename": str(metadata.get("filename") or "object"),
        }

    def store_from_file(
        self,
        publication_id: str,
        object_kind: str,
        item_id: str,
        source_path: str | Path,
        *,
        owner_ref: str,
        expected_size: int,
        expected_sha256: str,
    ) -> Path:
        """Promote a verified 7997 staging file into publication storage."""
        record = self.library._record(publication_id)
        if str(record.get("owner_ref") or "") != str(owner_ref or ""):
            raise PermissionError("research publication owner does not match")
        projection = self.library._projection(publication_id)
        metadata, target = self._entry(
            projection, publication_id, object_kind, item_id,
        )
        source = Path(source_path).expanduser().resolve()
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError("research object upload staging is unavailable")
        expected_size = int(expected_size)
        expected_sha256 = str(expected_sha256 or "").strip().lower()
        if expected_size < 0 or len(expected_sha256) != 64:
            raise ValueError("research object transfer metadata is invalid")
        descriptor_hash = str(metadata.get("content_hash") or "").strip().lower()
        if descriptor_hash and descriptor_hash != expected_sha256:
            raise ValueError("research object hash does not match publication")
        digest, size = _file_digest(source)
        if size != expected_size or digest != expected_sha256:
            raise ValueError("research object upload integrity check failed")
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError("research object destination is invalid")
        temporary = target.with_name(
            f".{target.name}.upload.{secrets.token_hex(8)}.tmp"
        )
        shutil.copyfile(source, temporary)
        try:
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        source.unlink(missing_ok=True)
        return target

    def _entry(
        self,
        projection: dict[str, Any],
        publication_id: str,
        object_kind: str,
        item_id: str,
    ) -> tuple[dict[str, Any], Path]:
        collections = {
            "research_asset": (
                "assets", "asset_id",
                lambda value: self.library._asset_path(publication_id, value),
            ),
            "research_attachment": (
                "attachments", "attachment_ref",
                lambda value: self.library._attachment_path(
                    publication_id, _attachment_id(value),
                ),
            ),
            "research_local_resource": (
                "local_resources", "resource_id",
                lambda value: self.library._local_resource_path(
                    publication_id, value,
                ),
            ),
        }
        selected = collections.get(str(object_kind))
        if selected is None:
            raise ValueError("research object kind is unsupported")
        collection_name, id_key, path_builder = selected
        metadata = next(
            (
                value for value in projection.get(collection_name, [])
                if str(value.get(id_key) or "") == str(item_id)
            ),
            None,
        )
        if not isinstance(metadata, dict):
            raise ValueError("research object was not found")
        return metadata, path_builder(str(item_id))


__all__ = ["PublicResearchObject", "PublicResearchObjectStore"]


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size

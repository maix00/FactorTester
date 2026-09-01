"""Durable local queue for shared research-report synchronization.

Research authoring is local-first.  This queue is only the bridge to an
optional Manager publication; it is not a source of truth for the report
tree.  Projection metadata is kept separately from object bytes so the
control request remains small and object bytes can still use 7997.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .object_uploads import ResearchObjectUpload
from .storage import atomic_json


SCHEMA_VERSION = 1
_PENDING_STATES = frozenset({"pending", "syncing"})
_OPERATION_KINDS = frozenset({"publish", "revoke"})


class PublicResearchOutbox:
    """Persist pending publication operations under one client root."""

    def __init__(self, client_root: Path) -> None:
        self.root = Path(client_root).expanduser().resolve() / "sync" / "public-research"
        self.lock_path = self.root / ".lock"

    def enqueue_publish(
        self,
        *,
        owner_ref: str,
        profile_ref: str,
        report_id: str,
        publication_key: str = "",
        branch_ref: str = "",
        visibility: str = "public",
        authorized_users: tuple[str, ...] = (),
        projection: dict[str, Any],
        public_title: str,
        show_profile: bool,
        uploads: tuple[ResearchObjectUpload, ...],
    ) -> str:
        report_id = _required(report_id, "report_id")
        projection_hash = _required(
            str(projection.get("projection_hash") or ""),
            "projection_hash",
        )
        publication_key = str(publication_key or report_id).strip()
        operation_id = _operation_id("publish", publication_key, projection_hash)
        operation_dir = self.root / operation_id
        with self._locked():
            self._mark_previous_publish_operations_locked(
                publication_key, superseded_by=operation_id,
            )
            operation_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_json(operation_dir / "projection.json", projection)
            object_rows = []
            objects_dir = operation_dir / "objects"
            objects_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            for index, upload in enumerate(uploads):
                object_name = f"{index:03d}-{upload.content_hash}.bin"
                object_path = objects_dir / object_name
                _atomic_bytes(object_path, upload.content)
                object_rows.append({
                    "object_kind": upload.object_kind,
                    "object_id": upload.object_id,
                    "filename": upload.filename,
                    "content_type": upload.content_type,
                    "content_hash": upload.content_hash,
                    "size_bytes": upload.size_bytes,
                    "path": f"objects/{object_name}",
                })
            atomic_json(operation_dir / "manifest.json", {
                "schema_version": SCHEMA_VERSION,
                "operation_id": operation_id,
                "kind": "publish",
                "state": "pending",
                "owner_ref": _required(owner_ref, "owner_ref"),
                "profile_ref": str(profile_ref or ""),
                "report_id": report_id,
                "publication_key": publication_key,
                "branch_ref": str(branch_ref or "").strip(),
                "visibility": str(visibility or "public").strip(),
                "authorized_users": sorted({
                    str(item).strip() for item in authorized_users if str(item).strip()
                }),
                "projection_hash": projection_hash,
                "generation": int(projection.get("generation") or 0),
                "public_title": str(public_title or "").strip(),
                "show_profile": bool(show_profile),
                "publication_id": "",
                "objects": object_rows,
                "attempts": 0,
                "created_at": time.time(),
                "updated_at": time.time(),
                "last_error": "",
            })
        return operation_id

    def enqueue_revoke(self, *, publication_id: str) -> str:
        publication_id = _required(publication_id, "publication_id")
        operation_id = _operation_id("revoke", publication_id, "")
        operation_dir = self.root / operation_id
        with self._locked():
            operation_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_json(operation_dir / "manifest.json", {
                "schema_version": SCHEMA_VERSION,
                "operation_id": operation_id,
                "kind": "revoke",
                "state": "pending",
                "publication_id": publication_id,
                "attempts": 0,
                "created_at": time.time(),
                "updated_at": time.time(),
                "last_error": "",
            })
        return operation_id

    def pending(self) -> list[dict[str, Any]]:
        """Return pending manifests without reading report or object bytes."""
        if not self.root.is_dir():
            return []
        values = []
        for operation_dir in sorted(self.root.iterdir()):
            if not operation_dir.is_dir() or operation_dir.name.startswith("."):
                continue
            try:
                manifest = _read_json(operation_dir / "manifest.json")
                _validate_manifest(manifest, operation_dir.name)
            except ValueError:
                # A corrupt queue item must be visible to diagnostics, but it
                # must not prevent other reports from syncing.
                continue
            if manifest["state"] in _PENDING_STATES:
                values.append(manifest)
        return sorted(values, key=lambda item: (
            float(item.get("created_at") or 0), item["operation_id"],
        ))

    def load(self, operation_id: str) -> dict[str, Any]:
        operation_id = _required(operation_id, "operation_id")
        operation_dir = self.root / operation_id
        manifest = _read_json(operation_dir / "manifest.json")
        _validate_manifest(manifest, operation_id)
        value = {"manifest": manifest, "directory": operation_dir}
        if manifest["kind"] != "publish":
            return value
        value["projection"] = _read_json(operation_dir / "projection.json")
        uploads: list[ResearchObjectUpload] = []
        for item in manifest["objects"]:
            path = operation_dir / str(item["path"])
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != item["content_hash"]:
                raise ValueError("public research outbox object hash mismatch")
            uploads.append(ResearchObjectUpload(
                object_kind=item["object_kind"],
                object_id=item["object_id"],
                filename=item["filename"],
                content_type=item["content_type"],
                content_hash=item["content_hash"],
                content=content,
            ))
        value["uploads"] = tuple(uploads)
        return value

    def update(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        operation_dir = self.root / _required(operation_id, "operation_id")
        with self._locked():
            manifest = _read_json(operation_dir / "manifest.json")
            _validate_manifest(manifest, operation_dir.name)
            manifest.update(changes, updated_at=time.time())
            atomic_json(operation_dir / "manifest.json", manifest)
        return manifest

    def save_publication_cache(self, reports: list[dict[str, Any]]) -> None:
        with self._locked():
            atomic_json(self.root / "remote-publications.json", {
                "schema_version": SCHEMA_VERSION,
                "reports": [item for item in reports if isinstance(item, dict)],
                "updated_at": time.time(),
            })

    def load_publication_cache(self) -> list[dict[str, Any]]:
        path = self.root / "remote-publications.json"
        if not path.is_file():
            return []
        value = _read_json(path)
        reports = value.get("reports")
        return [item for item in reports if isinstance(item, dict)] if isinstance(reports, list) else []

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _mark_previous_publish_operations_locked(
        self, publication_key: str, *, superseded_by: str,
    ) -> None:
        for operation_dir in self.root.iterdir() if self.root.is_dir() else ():
            if not operation_dir.is_dir() or operation_dir.name.startswith("."):
                continue
            try:
                manifest = _read_json(operation_dir / "manifest.json")
                _validate_manifest(manifest, operation_dir.name)
            except ValueError:
                continue
            if (
                manifest.get("kind") == "publish"
                and str(manifest.get("publication_key") or manifest.get("report_id"))
                == publication_key
                and manifest.get("state") in _PENDING_STATES
            ):
                manifest.update(
                    state="superseded", superseded_by=superseded_by,
                    updated_at=time.time(),
                )
                atomic_json(operation_dir / "manifest.json", manifest)


def _operation_id(kind: str, identity: str, revision: str) -> str:
    value = f"{kind}:{identity}:{revision}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:32]


def _required(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"public research outbox file is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"public research outbox file is invalid: {path}")
    return value


def _validate_manifest(value: dict[str, Any], operation_id: str) -> None:
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("operation_id") != operation_id
        or value.get("kind") not in _OPERATION_KINDS
        or value.get("state") not in {
            "pending", "syncing", "completed", "conflict", "superseded",
        }
    ):
        raise ValueError("public research outbox manifest is invalid")
    if value["kind"] == "publish":
        objects = value.get("objects")
        if not isinstance(objects, list):
            raise ValueError("public research publish outbox objects are invalid")
        for item in objects:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(field), str) and item[field]
                for field in (
                    "object_kind", "object_id", "filename", "content_type",
                    "content_hash", "path",
                )
            ):
                raise ValueError("public research outbox object metadata is invalid")
            path = Path(item["path"])
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("public research outbox object path is invalid")
            if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] < 0:
                raise ValueError("public research outbox object size is invalid")


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


__all__ = ["PublicResearchOutbox", "SCHEMA_VERSION"]

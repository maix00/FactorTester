"""Server-side mirror of reports uploaded by an owner's FTClient."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

from .metadata import normalize_build_source, provenance_fields
from .projection import chapter_projection, component_projection, projection_index
from .storage import atomic_json, locked_registry, read_json, read_registry

VISIBILITIES = {"private", "superiors", "authorized", "public"}


class PublicResearchLibrary:
    """Persist uploaded projections without resolving the owner's local files."""

    def __init__(self, root: Path, *, storage_server_id: str = "") -> None:
        self.root = root.resolve()
        self.registry_path = self.root / "publications.json"
        self.mirror_root = self.root / "mirrors"
        self.storage_server_id = str(storage_server_id or "").strip()

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        report_id = _required(payload, "report_id")
        publication_key = _optional_text(payload.get("publication_key")) or report_id
        branch_ref = _optional_text(payload.get("branch_ref"))
        owner_ref = _required(payload, "owner_ref")
        profile_ref = _optional_text(payload.get("profile_ref"))
        build_source = normalize_build_source(payload.get("build_source"))
        build_source_ref = _optional_text(payload.get("build_source_ref"))
        projection = _projection(payload.get("projection"), report_id)
        now = time.time()
        with locked_registry(self.root) as registry:
            record = _record_by_publication_key(registry, publication_key)
            if record is None:
                record = {
                    "publication_id": secrets.token_urlsafe(18),
                    "report_id": report_id,
                    "publication_key": publication_key,
                    "branch_ref": branch_ref,
                    "owner_ref": owner_ref,
                    "profile_ref": profile_ref,
                    "visibility": "private",
                    "auto_sync": True,
                    "relay_local_files": False,
                    "authorized_users": [],
                    "published_at": now,
                    "storage_server_id": self.storage_server_id,
                    "build_source": build_source,
                    "build_source_ref": build_source_ref,
                }
                registry["publications"].append(record)
            if record["owner_ref"] != owner_ref:
                raise PermissionError("report owner does not match")
            if str(record.get("report_id") or "") != report_id:
                raise PermissionError("publication key belongs to another report")
            _merge_build_metadata(
                record,
                build_source=build_source,
                build_source_ref=build_source_ref,
            )
            if profile_ref:
                record["profile_ref"] = profile_ref
            if self.storage_server_id:
                record["storage_server_id"] = self.storage_server_id
            if not record.get("auto_sync", True):
                return {"status": "disabled", "report_id": report_id}
            current_generation = int(record.get("generation") or -1)
            generation = int(projection["generation"])
            if generation < current_generation:
                return {
                    "status": "stale",
                    "report_id": report_id,
                    "generation": current_generation,
                }
            self._store_projection(record["publication_id"], projection)
            record.update(
                generation=generation,
                projection_hash=projection["projection_hash"],
                title=str(projection.get("title") or ""),
                synced_at=now,
                client_online_at=now,
            )
            publication_id = record["publication_id"]
        return {
            "status": "synced",
            "publication_id": publication_id,
            "generation": projection["generation"],
        }

    def configure(
        self,
        *,
        owner_ref: str,
        report_id: str,
        publication_key: str = "",
        projection: dict[str, Any] | None,
        visibility: str,
        auto_sync: bool,
        relay_local_files: bool,
        authorized_users: list[str],
        build_source: str = "",
        build_source_ref: str = "",
    ) -> dict[str, Any]:
        owner_ref = _required_text(owner_ref, "owner_ref")
        report_id = _required_text(report_id, "report_id")
        if visibility not in VISIBILITIES:
            raise ValueError("visibility is invalid")
        publication_key = str(publication_key or report_id).strip()
        existing = _record_by_publication_key(self._registry(), publication_key)
        requested_source = normalize_build_source(
            build_source,
            default=str(existing.get("build_source") or "client")
            if existing is not None else "client",
        )
        requested_source_ref = _optional_text(build_source_ref)
        users = sorted({
            _required_text(item, "authorized user")
            for item in authorized_users
            if str(item).strip() and str(item).strip() != owner_ref
        })
        value = (
            _projection(projection, report_id)
            if projection is not None
            else self._projection(str(existing["publication_id"]))
            if existing is not None
            else None
        )
        if value is None:
            raise ValueError("report must be uploaded before it can be configured")
        now = time.time()
        with locked_registry(self.root) as registry:
            record = _record_by_publication_key(registry, publication_key)
            if record is not None and record["owner_ref"] != owner_ref:
                raise PermissionError("report publication belongs to another user")
            if record is None:
                record = {
                    "publication_id": secrets.token_urlsafe(18),
                    "report_id": report_id,
                    "publication_key": publication_key,
                    "owner_ref": owner_ref,
                    "published_at": now,
                    "storage_server_id": self.storage_server_id,
                    "build_source": requested_source,
                    "build_source_ref": requested_source_ref,
                }
                registry["publications"].append(record)
            _merge_build_metadata(
                record,
                build_source=requested_source,
                build_source_ref=requested_source_ref,
            )
            record.update(
                visibility=visibility,
                auto_sync=bool(auto_sync),
                relay_local_files=bool(relay_local_files),
                authorized_users=users,
                generation=int(value["generation"]),
                projection_hash=value["projection_hash"],
                title=str(value.get("title") or ""),
                synced_at=now,
                client_online_at=now,
            )
            if self.storage_server_id:
                record["storage_server_id"] = self.storage_server_id
            publication_id = record["publication_id"]
            self._store_projection(publication_id, value)
        return self.owner_settings(publication_id, owner_ref)

    def owner_settings(self, publication_id: str, owner_ref: str) -> dict[str, Any]:
        record = self._record(publication_id)
        if record["owner_ref"] != owner_ref:
            raise PermissionError("report settings require the owner")
        return _owner_record(record)

    def publication_metadata(self, publication_id: str) -> dict[str, Any]:
        """Return sync-safe publication metadata without report bytes."""
        return _owner_record(self._record(publication_id))

    def list_owner(self, owner_ref: str) -> list[dict[str, Any]]:
        return [
            _owner_record(record)
            for record in self._registry()["publications"]
            if record["owner_ref"] == owner_ref
        ]

    def list_metadata(self) -> list[dict[str, Any]]:
        """Return all publication metadata for a local sync reconciliation."""
        return [
            _owner_record(record)
            for record in self._registry()["publications"]
        ]

    def list_visible(self, viewer_ref: str | None) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for record in self._registry()["publications"]:
            if not _can_read(record, viewer_ref):
                continue
            try:
                title = str(record.get("title") or "")
                generation = record.get("generation")
                if not title or not isinstance(generation, int):
                    index = self._read_index(
                        record["publication_id"],
                        expected_hash=str(record.get("projection_hash") or ""),
                    )
                    title = str(index.get("title") or title)
                    generation = index.get("generation", generation)
            except ValueError:
                continue
            values.append({
                "publication_id": record["publication_id"],
                "report_id": record["report_id"],
                "publication_key": record.get("publication_key") or record["report_id"],
                "branch_ref": record.get("branch_ref") or "",
                "owner_ref": record["owner_ref"],
                "profile_ref": record.get("profile_ref") or "",
                "title": title,
                "generation": generation,
                "updated_at": record.get("synced_at") or 0,
                "visibility": record["visibility"],
                "is_owned": viewer_ref == record["owner_ref"],
                "projection_hash": record.get("projection_hash") or "",
                "storage_server_id": record.get("storage_server_id") or self.storage_server_id,
                "href": f"/research/{record['publication_id']}",
                **provenance_fields(record),
            })
        return sorted(values, key=lambda item: item["updated_at"], reverse=True)

    def projection(
        self, publication_id: str, viewer_ref: str | None,
    ) -> dict[str, Any]:
        record = self._record(publication_id)
        if not _can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        value = self._projection(publication_id)
        value["access"] = {
            "visibility": record["visibility"],
            **provenance_fields(record),
            "can_manage": viewer_ref == record["owner_ref"],
            "local_file_relay": bool(record.get("relay_local_files")),
            "owner_client_online": _client_online(record),
        }
        return value

    def index(
        self, publication_id: str, viewer_ref: str | None,
    ) -> dict[str, Any]:
        """Read only chapter metadata before the selected chapter is opened."""
        record = self._record(publication_id)
        if not _can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        value = self._read_index(
            publication_id,
            expected_hash=str(record.get("projection_hash") or ""),
        )
        value["access"] = {
            "visibility": record["visibility"],
            **provenance_fields(record),
            "can_manage": viewer_ref == record["owner_ref"],
            "local_file_relay": bool(record.get("relay_local_files")),
            "owner_client_online": _client_online(record),
        }
        return value

    def chapter(
        self, publication_id: str, chapter_id: str, viewer_ref: str | None,
        *, include_content: bool = True,
    ) -> dict[str, Any]:
        """Read one report chapter and its descendants on demand."""
        record = self._record(publication_id)
        if not _can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        path = self._chapter_path(publication_id, chapter_id)
        try:
            value = read_json(path, "research chapter")
            if (
                value.get("schema_version") != 2
                or str(value.get("chapter_id") or "") != str(chapter_id)
                or (
                    record.get("projection_hash")
                    and value.get("projection_hash") != record["projection_hash"]
                )
            ):
                raise ValueError("research chapter sidecar is invalid")
        except ValueError:
            # Rebuild only for a publication created before chapter sidecars
            # existed, or after an interrupted publication write.
            value = chapter_projection(self._projection(publication_id), chapter_id)
            atomic_json(path, value)
        if not include_content:
            value = chapter_projection(value, chapter_id, include_content=False)
        value["access"] = {
            "visibility": record["visibility"],
            **provenance_fields(record),
            "can_manage": viewer_ref == record["owner_ref"],
            "local_file_relay": bool(record.get("relay_local_files")),
            "owner_client_online": _client_online(record),
        }
        return value

    def component(
        self, publication_id: str, chapter_id: str, component_id: str,
        viewer_ref: str | None,
    ) -> dict[str, Any]:
        """Read one component body after a metadata-only chapter load."""
        record = self._record(publication_id)
        if not _can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        chapter = self.chapter(
            publication_id, chapter_id, viewer_ref, include_content=True,
        )
        value = component_projection(chapter, chapter_id, component_id)
        value["access"] = {
            "visibility": record["visibility"],
            **provenance_fields(record),
            "can_manage": viewer_ref == record["owner_ref"],
            "local_file_relay": bool(record.get("relay_local_files")),
            "owner_client_online": _client_online(record),
        }
        return value

    def asset(
        self, publication_id: str, asset_id: str, viewer_ref: str | None,
    ) -> tuple[bytes, str, str]:
        record = self._record(publication_id)
        if not _can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        metadata = next((item for item in self._projection(publication_id).get("assets", [])
                         if item.get("asset_id") == asset_id), None)
        if metadata is None:
            raise ValueError("research asset was not found")
        path = self._asset_path(publication_id, asset_id)
        if not path.is_file():
            raise ValueError("research asset is unavailable")
        raw = path.read_bytes()
        if metadata.get("content_hash") and hashlib.sha256(raw).hexdigest() != metadata["content_hash"]:
            raise ValueError("research asset integrity check failed")
        content_type = str(metadata.get("media_type") or mimetypes.guess_type(str(metadata.get("filename") or ""))[0] or "application/octet-stream")
        return raw, content_type, str(metadata.get("filename") or "asset")

    def attachment(
        self, publication_id: str, attachment_ref: str, viewer_ref: str | None,
    ) -> tuple[bytes, str, str]:
        """Read a content-addressed related-object snapshot."""
        record = self._record(publication_id)
        if not _can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        metadata = next((item for item in self._projection(publication_id).get("attachments", [])
                         if item.get("attachment_ref") == attachment_ref), None)
        if metadata is None:
            raise ValueError("research attachment was not found")
        attachment_id = _attachment_id(attachment_ref)
        path = self._attachment_path(publication_id, attachment_id)
        if not path.is_file():
            raise ValueError("research attachment is unavailable")
        raw = path.read_bytes()
        if metadata.get("content_hash") and hashlib.sha256(raw).hexdigest() != metadata["content_hash"]:
            raise ValueError("research attachment integrity check failed")
        content_type = str(metadata.get("media_type") or mimetypes.guess_type(str(metadata.get("filename") or ""))[0] or "application/octet-stream")
        return raw, content_type, str(metadata.get("filename") or "attachment")

    def local_resource(
        self, publication_id: str, resource_id: str, viewer_ref: str | None,
    ) -> tuple[bytes, str, str]:
        """Read a bounded local-file snapshot uploaded with a publication."""
        record = self._record(publication_id)
        if not _can_read(record, viewer_ref):
            raise PermissionError("research report access is not authorized")
        if not re.fullmatch(r"[a-f0-9]{24}", resource_id):
            raise ValueError("research local resource id is invalid")
        metadata = next((item for item in self._projection(publication_id).get("local_resources", [])
                         if item.get("resource_id") == resource_id), None)
        if metadata is None:
            raise ValueError("research local resource was not found")
        path = self._local_resource_path(publication_id, resource_id)
        if not path.is_file():
            raise ValueError("research local resource is unavailable")
        raw = path.read_bytes()
        if metadata.get("content_hash") and hashlib.sha256(raw).hexdigest() != metadata["content_hash"]:
            raise ValueError("research local resource integrity check failed")
        content_type = str(metadata.get("media_type") or mimetypes.guess_type(str(metadata.get("filename") or ""))[0] or "application/octet-stream")
        return raw, content_type, str(metadata.get("filename") or "resource")

    def touch_client(self, owner_ref: str, report_ids: list[str]) -> list[str]:
        now = time.time()
        publications: list[str] = []
        with locked_registry(self.root) as registry:
            wanted = set(report_ids)
            for record in registry["publications"]:
                if record["owner_ref"] == owner_ref and record["report_id"] in wanted:
                    record["client_online_at"] = now
                    publications.append(record["publication_id"])
        return publications

    def revoke_publication(self, publication_id: str) -> dict[str, Any]:
        """Remove one publication and its mirrored bytes from the registry."""
        publication_id = _required_text(publication_id, "publication_id")
        with locked_registry(self.root) as registry:
            record = next(
                (
                    item for item in registry["publications"]
                    if item.get("publication_id") == publication_id
                ),
                None,
            )
            if record is None:
                raise ValueError("research publication was not found")
            registry["publications"] = [
                item for item in registry["publications"]
                if item.get("publication_id") != publication_id
            ]
        self._mirror_path(publication_id).unlink(missing_ok=True)
        self._index_path(publication_id).unlink(missing_ok=True)
        shutil.rmtree(self.mirror_root / publication_id, ignore_errors=True)
        return {
            "status": "revoked",
            "publication_id": publication_id,
            "report_id": str(record.get("report_id") or ""),
        }

    def publication_for_report(self, report_id: str) -> str | None:
        record = _record_by_report(self._registry(), report_id)
        return str(record["publication_id"]) if record else None

    def _record(self, publication_id: str) -> dict[str, Any]:
        record = next((
            item for item in self._registry()["publications"]
            if item["publication_id"] == publication_id
        ), None)
        if record is None:
            raise ValueError("research publication was not found")
        return record

    def _projection(self, publication_id: str) -> dict[str, Any]:
        value = read_json(self._mirror_path(publication_id), "research mirror")
        if value.get("schema_version") != 2:
            raise ValueError("research mirror is invalid")
        return value

    def _read_index(self, publication_id: str, *, expected_hash: str) -> dict[str, Any]:
        """Read the persisted chapter index without decoding the full report."""
        path = self._index_path(publication_id)
        try:
            value = read_json(path, "research report index")
            if (
                value.get("schema_version") == 2
                and isinstance(value.get("chapters"), list)
                and (not expected_hash or value.get("projection_hash") == expected_hash)
            ):
                return value
        except ValueError:
            pass

        # A publication created before the sidecar existed is rebuilt once.  The
        # hash check also repairs a sidecar left behind by an interrupted sync.
        value = projection_index(self._projection(publication_id))
        atomic_json(path, value)
        return value

    def _store_projection(self, publication_id: str, projection: dict[str, Any]) -> None:
        assets_root = self.mirror_root / publication_id / "assets"
        assets_root.mkdir(parents=True, exist_ok=True)
        attachments_root = self.mirror_root / publication_id / "attachments"
        attachments_root.mkdir(parents=True, exist_ok=True)
        resources_root = self.mirror_root / publication_id / "local-resources"
        resources_root.mkdir(parents=True, exist_ok=True)
        chapters_root = self.mirror_root / publication_id / "chapters"
        chapters_root.mkdir(parents=True, exist_ok=True)
        clean_assets = []
        asset_ids: set[str] = set()
        for item in projection.get("assets", []):
            value = dict(item)
            encoded = value.pop("content_base64", "")
            asset_id = str(value.get("asset_id") or "")
            if asset_id:
                asset_ids.add(asset_id)
            if encoded:
                raw = base64.b64decode(encoded, validate=True)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError("research asset exceeds size limit")
                (assets_root / str(value["asset_id"])).write_bytes(raw)
            clean_assets.append(value)
        clean_attachments = []
        attachment_ids: set[str] = set()
        attachment_total = 0
        for item in projection.get("attachments", []):
            value = dict(item)
            encoded = value.pop("content_base64", "")
            attachment_ref = str(value.get("attachment_ref") or "")
            if attachment_ref:
                attachment_ids.add(_attachment_id(attachment_ref))
            if not encoded or not attachment_ref:
                clean_attachments.append(value)
                continue
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("research attachment exceeds size limit")
            attachment_total += len(raw)
            if attachment_total > 20 * 1024 * 1024:
                raise ValueError("research attachments exceed total size limit")
            digest = str(value.get("content_hash") or "")
            if digest and hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("research attachment hash mismatch")
            (attachments_root / _attachment_id(attachment_ref)).write_bytes(raw)
            clean_attachments.append(value)
        clean_resources = []
        resource_ids: set[str] = set()
        resource_total = 0
        for item in projection.get("local_resources", []):
            value = dict(item)
            encoded = value.pop("content_base64", "")
            resource_id = str(value.get("resource_id") or "")
            if not re.fullmatch(r"[a-f0-9]{24}", resource_id):
                raise ValueError("research local resource id is invalid")
            resource_ids.add(resource_id)
            if encoded:
                raw = base64.b64decode(encoded, validate=True)
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError("research local resource exceeds size limit")
                resource_total += len(raw)
                if resource_total > 20 * 1024 * 1024:
                    raise ValueError("research local resources exceed total size limit")
                digest = str(value.get("content_hash") or "")
                if digest and hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError("research local resource hash mismatch")
                (resources_root / resource_id).write_bytes(raw)
            clean_resources.append(value)
        for path in assets_root.iterdir():
            if path.is_file() and path.name not in asset_ids:
                path.unlink()
        for path in attachments_root.iterdir():
            if path.is_file() and path.name not in attachment_ids:
                path.unlink()
        for path in resources_root.iterdir():
            if path.is_file() and path.name not in resource_ids:
                path.unlink()
        clean = {
            **projection,
            "assets": clean_assets,
            "attachments": clean_attachments,
            "local_resources": clean_resources,
        }
        atomic_json(self._mirror_path(publication_id), clean)
        atomic_json(self._index_path(publication_id), projection_index(clean))
        chapter_ids = {
            str(item.get("component_id") or "")
            for item in clean.get("components", [])
            if item.get("kind") == "chapter" and item.get("parent_id") is None
        }
        for chapter_id in chapter_ids:
            atomic_json(
                self._chapter_path(publication_id, chapter_id),
                chapter_projection(clean, chapter_id),
            )
        for path in chapters_root.glob("*.json"):
            if path.stem not in {_chapter_storage_id(item) for item in chapter_ids}:
                path.unlink(missing_ok=True)

    def _asset_path(self, publication_id: str, asset_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", asset_id):
            raise ValueError("research asset id is invalid")
        return self.mirror_root / publication_id / "assets" / asset_id

    def _attachment_path(self, publication_id: str, attachment_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", attachment_id):
            raise ValueError("research attachment id is invalid")
        return self.mirror_root / publication_id / "attachments" / attachment_id

    def _local_resource_path(self, publication_id: str, resource_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{24}", resource_id):
            raise ValueError("research local resource id is invalid")
        return self.mirror_root / publication_id / "local-resources" / resource_id

    def _mirror_path(self, publication_id: str) -> Path:
        return self.mirror_root / f"{publication_id}.json"

    def _index_path(self, publication_id: str) -> Path:
        return self.mirror_root / f"{publication_id}.index.json"

    def _chapter_path(self, publication_id: str, chapter_id: str) -> Path:
        return self.mirror_root / publication_id / "chapters" / f"{_chapter_storage_id(chapter_id)}.json"

    def _registry(self) -> dict[str, Any]:
        return read_registry(self.registry_path)


def _projection(value: Any, report_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        raise ValueError("uploaded research projection is invalid")
    if value.get("report_id") != report_id:
        raise ValueError("uploaded report identity does not match")
    if not isinstance(value.get("generation"), int) or value["generation"] < 0:
        raise ValueError("uploaded report generation is invalid")
    if not isinstance(value.get("components"), list):
        raise ValueError("uploaded report components are invalid")
    if not isinstance(value.get("local_resources", []), list):
        raise ValueError("uploaded research local resources are invalid")
    if not isinstance(value.get("projection_hash"), str):
        raise ValueError("uploaded report hash is invalid")
    return value


def _required(value: dict[str, Any], key: str) -> str:
    return _required_text(value.get(key), key)


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text.encode("utf-8")) > 512:
        raise ValueError(f"{label} is invalid")
    return text


def _optional_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text.encode("utf-8")) > 512:
        raise ValueError("text is invalid")
    return text


def _attachment_id(attachment_ref: str) -> str:
    prefix = "attachment:sha256:"
    if not attachment_ref.startswith(prefix):
        raise ValueError("research attachment ref is invalid")
    value = attachment_ref[len(prefix):]
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("research attachment ref is invalid")
    return value


def _chapter_storage_id(chapter_id: str) -> str:
    return hashlib.sha256(str(chapter_id).encode("utf-8")).hexdigest()[:32]


def _record_by_report(
    registry: dict[str, Any], report_id: str,
) -> dict[str, Any] | None:
    return next((
        item for item in registry["publications"]
        if item.get("report_id") == report_id
    ), None)


def _record_by_publication_key(
    registry: dict[str, Any], publication_key: str,
) -> dict[str, Any] | None:
    return next((
        item for item in registry["publications"]
        if str(item.get("publication_key") or item.get("report_id") or "")
        == publication_key
    ), None)


def _can_read(record: dict[str, Any], viewer_ref: str | None) -> bool:
    if viewer_ref == record["owner_ref"]:
        return True
    if record.get("visibility") == "public":
        return True
    return bool(
        viewer_ref
        and record.get("visibility") in {"superiors", "authorized"}
        and viewer_ref in set(record.get("authorized_users") or [])
    )


def _client_online(record: dict[str, Any]) -> bool:
    return time.time() - float(record.get("client_online_at") or 0) <= 45


def _merge_build_metadata(
    record: dict[str, Any], *, build_source: str, build_source_ref: str,
) -> None:
    """Preserve one report's construction identity across later syncs."""
    current = normalize_build_source(record.get("build_source"))
    if current != build_source and record.get("build_source") is not None:
        raise PermissionError("report construction source does not match")
    record["build_source"] = build_source
    if build_source_ref:
        current_ref = str(record.get("build_source_ref") or "").strip()
        if current_ref and current_ref != build_source_ref:
            raise PermissionError("report construction source reference does not match")
        record["build_source_ref"] = build_source_ref


def _owner_record(record: dict[str, Any]) -> dict[str, Any]:
    value = {
        key: record.get(key)
        for key in (
            "publication_id", "report_id", "owner_ref", "profile_ref", "visibility",
            "publication_key", "branch_ref",
            "auto_sync", "relay_local_files", "authorized_users",
            "generation", "synced_at",
            "title", "projection_hash", "published_at", "storage_server_id",
        )
    } | {
        "owner_client_online": _client_online(record),
        "updated_at": record.get("synced_at") or 0,
    }
    value.update(provenance_fields(record))
    return value

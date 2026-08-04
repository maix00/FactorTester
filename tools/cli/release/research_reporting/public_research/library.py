"""Server-side mirror of reports uploaded by an owner's FTClient."""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any

from .storage import atomic_json, locked_registry, read_json, read_registry


VISIBILITIES = {"private", "authorized", "public"}


class PublicResearchLibrary:
    """Persist uploaded projections without resolving the owner's local files."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.registry_path = self.root / "publications.json"
        self.mirror_root = self.root / "mirrors"

    def sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        report_id = _required(payload, "report_id")
        owner_ref = _required(payload, "owner_ref")
        projection = _projection(payload.get("projection"), report_id)
        now = time.time()
        with locked_registry(self.root) as registry:
            record = _record_by_report(registry, report_id)
            if record is None:
                record = {
                    "publication_id": secrets.token_urlsafe(18),
                    "report_id": report_id,
                    "owner_ref": owner_ref,
                    "visibility": "private",
                    "auto_sync": True,
                    "relay_local_files": False,
                    "authorized_users": [],
                    "published_at": now,
                }
                registry["publications"].append(record)
            if record["owner_ref"] != owner_ref:
                raise PermissionError("report owner does not match")
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
            atomic_json(self._mirror_path(record["publication_id"]), projection)
            record.update(
                generation=generation,
                projection_hash=projection["projection_hash"],
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
        projection: dict[str, Any] | None,
        visibility: str,
        auto_sync: bool,
        relay_local_files: bool,
        authorized_users: list[str],
    ) -> dict[str, Any]:
        owner_ref = _required_text(owner_ref, "owner_ref")
        report_id = _required_text(report_id, "report_id")
        if visibility not in VISIBILITIES:
            raise ValueError("visibility is invalid")
        users = sorted({
            _required_text(item, "authorized user")
            for item in authorized_users
            if str(item).strip() and str(item).strip() != owner_ref
        })
        existing = _record_by_report(self._registry(), report_id)
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
            record = _record_by_report(registry, report_id)
            if record is not None and record["owner_ref"] != owner_ref:
                raise PermissionError("report publication belongs to another user")
            if record is None:
                record = {
                    "publication_id": secrets.token_urlsafe(18),
                    "report_id": report_id,
                    "owner_ref": owner_ref,
                    "published_at": now,
                }
                registry["publications"].append(record)
            record.update(
                visibility=visibility,
                auto_sync=bool(auto_sync),
                relay_local_files=bool(relay_local_files),
                authorized_users=users,
                generation=int(value["generation"]),
                projection_hash=value["projection_hash"],
                synced_at=now,
                client_online_at=now,
            )
            publication_id = record["publication_id"]
            atomic_json(self._mirror_path(publication_id), value)
        return self.owner_settings(publication_id, owner_ref)

    def owner_settings(self, publication_id: str, owner_ref: str) -> dict[str, Any]:
        record = self._record(publication_id)
        if record["owner_ref"] != owner_ref:
            raise PermissionError("report settings require the owner")
        return _owner_record(record)

    def list_owner(self, owner_ref: str) -> list[dict[str, Any]]:
        return [
            _owner_record(record)
            for record in self._registry()["publications"]
            if record["owner_ref"] == owner_ref
        ]

    def list_visible(self, viewer_ref: str | None) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for record in self._registry()["publications"]:
            if not _can_read(record, viewer_ref):
                continue
            try:
                projection = self._projection(record["publication_id"])
            except ValueError:
                continue
            values.append({
                "publication_id": record["publication_id"],
                "report_id": record["report_id"],
                "title": projection["title"],
                "generation": projection["generation"],
                "updated_at": record.get("synced_at") or 0,
                "visibility": record["visibility"],
                "is_owned": viewer_ref == record["owner_ref"],
                "href": f"/research/{record['publication_id']}",
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
            "can_manage": viewer_ref == record["owner_ref"],
            "local_file_relay": bool(record.get("relay_local_files")),
            "owner_client_online": _client_online(record),
        }
        return value

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

    def _mirror_path(self, publication_id: str) -> Path:
        return self.mirror_root / f"{publication_id}.json"

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


def _record_by_report(
    registry: dict[str, Any], report_id: str,
) -> dict[str, Any] | None:
    return next((
        item for item in registry["publications"]
        if item.get("report_id") == report_id
    ), None)


def _can_read(record: dict[str, Any], viewer_ref: str | None) -> bool:
    if viewer_ref == record["owner_ref"]:
        return True
    if record.get("visibility") == "public":
        return True
    return bool(
        viewer_ref
        and record.get("visibility") == "authorized"
        and viewer_ref in set(record.get("authorized_users") or [])
    )


def _client_online(record: dict[str, Any]) -> bool:
    return time.time() - float(record.get("client_online_at") or 0) <= 45


def _owner_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "publication_id", "report_id", "owner_ref", "visibility",
            "auto_sync", "relay_local_files", "authorized_users",
            "generation", "synced_at",
        )
    } | {"owner_client_online": _client_online(record)}

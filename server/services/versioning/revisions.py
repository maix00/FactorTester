"""Common revision envelope for factor families, strategies and product groups.

This module owns revision identity and the source-free sync manifest. Domain
stores remain the byte authorities: factor and strategy source is transferred
through the existing object adapter, while product-group definitions fit in
the bounded account-domain metadata row. All manifests use the existing
account-domain outbox/cursor/conflict transport.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any


REVISION_ENTITY_TYPE = "versioned_object_revision"
VERSIONED_OBJECT_KINDS = frozenset({"factor_family", "user_strategy", "product_group"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCOPES = frozenset({"private", "superiors", "authorized", "public"})


def build_revision_manifest(
    *,
    object_kind: str,
    object_ref: str,
    revision_ref: str,
    content_sha256: str,
    owner_ref: str,
    storage_server_id: str,
    created_at: float,
    created_by: str = "",
    revision_number: int | None = None,
    visibility: str = "private",
    authorized_users: list[str] | tuple[str, ...] = (),
    object_bytes: int | None = None,
    source_entity_type: str = "",
) -> dict[str, Any]:
    """Validate and return the shared immutable, source-free revision record."""
    kind = str(object_kind or "").strip()
    if kind not in VERSIONED_OBJECT_KINDS:
        raise ValueError("unsupported versioned object kind")
    obj = _required(object_ref, "object_ref", 512)
    revision = _required(revision_ref, "revision_ref", 512)
    owner = _required(owner_ref, "owner_ref", 256)
    server = _required(storage_server_id, "storage_server_id", 128)
    digest = str(content_sha256 or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError("content_sha256 must be a SHA-256 digest")
    created = float(created_at)
    if not math.isfinite(created) or created <= 0:
        raise ValueError("created_at must be a positive finite timestamp")
    number = None if revision_number is None else int(revision_number)
    if number is not None and number < 1:
        raise ValueError("revision_number must be positive")
    scope = str(visibility or "private").strip().lower()
    if scope not in _SCOPES:
        raise ValueError("unsupported revision visibility")
    size = None if object_bytes is None else int(object_bytes)
    if size is not None and size < 0:
        raise ValueError("object_bytes cannot be negative")
    return {
        "schema_version": 1,
        "object_kind": kind,
        "object_ref": obj,
        "revision_ref": revision,
        "revision_number": number,
        "content_sha256": digest,
        "owner_ref": owner,
        "created_at": created,
        "created_by": str(created_by or "").strip()[:256],
        "visibility": scope,
        "authorized_users": sorted({str(item).strip() for item in authorized_users if str(item).strip()}),
        "storage_server_id": server,
        "object_bytes": size,
        "source_entity_type": str(source_entity_type or "").strip()[:64],
    }


def revision_entity_id(object_kind: str, object_ref: str, revision_ref: str) -> str:
    """Return a bounded deterministic sync key; exact refs remain in payload."""
    kind = str(object_kind or "").strip()
    if kind not in VERSIONED_OBJECT_KINDS:
        raise ValueError("unsupported versioned object kind")
    obj = _required(object_ref, "object_ref", 512)
    revision = _required(revision_ref, "revision_ref", 512)
    object_key = hashlib.sha256(obj.encode("utf-8")).hexdigest()[:32]
    revision_key = hashlib.sha256(revision.encode("utf-8")).hexdigest()[:32]
    return f"v1:{kind}:{object_key}:{revision_key}"


def enqueue_revision(
    local_store: Any,
    *,
    principal: str,
    manager_id: str,
    manifest: Mapping[str, Any],
    object_definition: Mapping[str, Any] | None = None,
    connection: Any = None,
) -> str:
    """Durably queue one immutable revision in the existing local outbox."""
    value = dict(manifest)
    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("unsupported revision manifest schema")
    kind = str(value.get("object_kind") or "")
    object_ref = str(value.get("object_ref") or "")
    revision_ref = str(value.get("revision_ref") or "")
    payload: dict[str, Any] = _sync_payload(value)
    if object_definition is not None:
        payload["object_definition"] = dict(object_definition)
    from server.manager.storage.account_domain.payloads import public_payload

    payload = public_payload(payload)
    identifier = revision_entity_id(kind, object_ref, revision_ref)
    existing = local_store.get_entity(
        str(principal or "").strip(), REVISION_ENTITY_TYPE, identifier,
    )
    if existing is not None:
        _assert_immutable(existing, payload)
        return ""
    return local_store.upsert_local(
        principal=str(principal or "").strip(),
        entity_type=REVISION_ENTITY_TYPE,
        entity_id=identifier,
        payload=payload,
        manager_id=str(manager_id or "local"),
        connection=connection,
    )


def publish_revision(
    sync: Any,
    *,
    principal: str,
    manifest: Mapping[str, Any],
    object_definition: Mapping[str, Any] | None = None,
    flush: bool = False,
) -> dict[str, Any]:
    """Queue a common revision manifest through AccountDomainSyncService."""
    value = dict(manifest)
    kind = str(value.get("object_kind") or "")
    object_ref = str(value.get("object_ref") or "")
    revision_ref = str(value.get("revision_ref") or "")
    payload: dict[str, Any] = _sync_payload(value)
    if object_definition is not None:
        payload["object_definition"] = dict(object_definition)
    identifier = revision_entity_id(kind, object_ref, revision_ref)
    existing = sync.local.get_entity(principal, REVISION_ENTITY_TYPE, identifier)
    if existing is not None:
        _assert_immutable(existing, payload)
        return {
            "status": "synced",
            "idempotent": True,
            "principal": principal,
            "entity_type": REVISION_ENTITY_TYPE,
            "entity_id": identifier,
        }
    return sync.upsert(
        principal,
        REVISION_ENTITY_TYPE,
        identifier,
        payload,
        flush=flush,
    )


def list_revision_manifests(
    local_store: Any,
    *,
    principal: str,
    object_kind: str = "",
    object_ref: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read a bounded local revision index without loading source bytes."""
    kind = str(object_kind or "").strip()
    if kind and kind not in VERSIONED_OBJECT_KINDS:
        raise ValueError("unsupported versioned object kind")
    reference = str(object_ref or "").strip()
    bounded = min(200, max(1, int(limit)))
    rows = local_store.list_entities(
        principal=str(principal or "").strip(),
        entity_type=REVISION_ENTITY_TYPE,
        include_shared=True,
        include_deleted=False,
    )
    values = []
    for row in rows:
        payload = row.get("payload") if isinstance(row, Mapping) else None
        manifest = payload.get("revision_manifest") if isinstance(payload, Mapping) else None
        if not isinstance(manifest, Mapping):
            continue
        if kind and manifest.get("object_kind") != kind:
            continue
        if reference and manifest.get("object_ref") != reference:
            continue
        values.append(dict(manifest))
    values.sort(key=lambda item: (
        -float(item.get("created_at") or 0),
        str(item.get("object_kind") or ""),
        str(item.get("object_ref") or ""),
        str(item.get("revision_ref") or ""),
    ))
    return values[:bounded]


def canonical_sha256(value: Mapping[str, Any]) -> tuple[str, bytes]:
    """Hash canonical JSON metadata for a domain-owned immutable revision."""
    raw = json.dumps(
        dict(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), raw


def _required(value: object, field: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(ord(char) < 32 for char in text):
        raise ValueError(f"{field} is invalid")
    return text


def _sync_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror access and byte-provider fields for the shared sync transport."""
    value = dict(manifest)
    return {
        "revision_manifest": value,
        "owner_ref": value.get("owner_ref", ""),
        "visibility": value.get("visibility", "private"),
        "authorized_users": list(value.get("authorized_users") or []),
        "storage_server_id": value.get("storage_server_id", ""),
    }


def _assert_immutable(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> None:
    if bool(existing.get("deleted")):
        raise ValueError("an immutable revision cannot be restored or replaced")
    old_payload = existing.get("payload")
    if not isinstance(old_payload, Mapping):
        raise ValueError("existing revision manifest is invalid")
    old = old_payload.get("revision_manifest")
    new = incoming.get("revision_manifest")
    if not isinstance(old, Mapping) or not isinstance(new, Mapping):
        raise ValueError("revision manifest is invalid")
    if any(old.get(key) != new.get(key) for key in (
        "schema_version", "object_kind", "object_ref", "revision_ref", "content_sha256",
    )):
        raise ValueError("immutable revision identity or content hash changed")
    old_definition = old_payload.get("object_definition")
    new_definition = incoming.get("object_definition")
    if old_definition is not None and new_definition is not None and old_definition != new_definition:
        raise ValueError("immutable revision definition changed")

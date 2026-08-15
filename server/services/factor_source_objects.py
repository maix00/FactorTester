"""Source-free factor object references and local hydration."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from scripts.data_dir import CACHE_DB_PATH
from tools.cli.factor_subject_refs import split_owner_qualified_factor_family


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def portable_source_path(canonical_ref: str) -> str:
    digest = hashlib.sha256(canonical_ref.encode("utf-8")).hexdigest()
    return f"manager_factor_sources/{digest}.py"


def _object_manifest(
    item: dict[str, Any],
    *,
    owner: str = "",
    storage_server_id: str = "",
) -> dict[str, Any]:
    """Normalize one local source entry into a source-free object reference."""
    canonical_ref = str(item.get("canonical_family_ref") or "").strip()
    factor_id = str(item.get("factor_id") or "").strip()
    if not canonical_ref and factor_id and owner:
        canonical_ref = f"{owner}:{factor_id}"
    if not canonical_ref:
        # Preserve the old helper for legacy entries without a family identity.
        return {
            key: value for key, value in item.items() if key != "source_code"
        }
    source_owner, parsed_factor_id = split_owner_qualified_factor_family(
        canonical_ref,
    )
    if source_owner is None or not parsed_factor_id:
        raise ValueError("factor source object identity is invalid")
    factor_id = factor_id or parsed_factor_id
    if factor_id != parsed_factor_id:
        raise ValueError("factor source object factor id does not match identity")
    source_kind = str(item.get("source_kind") or "").strip()
    if not source_kind:
        source_kind = "public" if source_owner == "public" else "custom"
    source_policy = str(item.get("source_access_policy") or "").strip()
    if not source_policy:
        source_policy = "transient_run_source"
    source_hash = str(item.get("source_sha256") or "").strip().lower()
    source_bytes = int(item.get("source_bytes") or -1)
    if not _SHA256.fullmatch(source_hash) or source_bytes < 0:
        raise ValueError("factor source object metadata is invalid")
    return {
        "canonical_family_ref": canonical_ref,
        "source_kind": source_kind,
        "source_owner": source_owner,
        "source_access_policy": source_policy,
        "factor_id": factor_id,
        "path": portable_source_path(canonical_ref),
        "source_sha256": source_hash,
        "source_bytes": source_bytes,
        "object_kind": "factor_source",
        "object_id": canonical_ref,
        "storage_server_id": str(
            item.get("storage_server_id") or storage_server_id or ""
        ).strip(),
    }


def source_free_manifest(
    entries: Iterable[dict[str, Any]],
    *,
    owner: str = "",
    storage_server_id: str = "",
) -> list[dict[str, Any]]:
    return [
        _object_manifest(
            item, owner=owner, storage_server_id=storage_server_id,
        )
        for item in entries
    ]


def source_transfer_manifest(
    entries: Iterable[dict[str, Any]],
    *,
    owner: str = "",
    storage_server_id: str = "",
) -> list[dict[str, Any]]:
    """Normalize source entries for the origin-side 7997 uploader.

    The source-free manifest deliberately removes ``source_code``.  The
    origin uploader needs the same canonical identity plus the source body,
    but this value never crosses the Manager 7998 run-context boundary.
    """
    result: list[dict[str, Any]] = []
    for item in entries:
        normalized = _object_manifest(
            item, owner=owner, storage_server_id=storage_server_id,
        )
        source = item.get("source_code")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("factor source transfer body is unavailable")
        result.append({**normalized, "source_code": source})
    return result


def source_free_context(
    context: dict[str, Any],
    *,
    owner: str,
    storage_server_id: str = "",
) -> dict[str, Any]:
    """Remove source text from a Manager-to-Manager Run context."""
    value = deepcopy(context)
    prepared = value.get("prepared")
    if not isinstance(prepared, dict):
        raise ValueError("manager run context is missing its prepared request")
    sources = [
        item for item in [
            *(prepared.get("transient_sources") or []),
            *(prepared.get("portable_factor_sources") or []),
        ]
        if isinstance(item, dict)
    ]
    prepared["transient_sources"] = []
    prepared["portable_factor_sources"] = source_free_manifest(
        sources,
        owner=owner,
        storage_server_id=storage_server_id,
    )
    return value


def hydrate_source_free_entries(
    entries: Iterable[dict[str, Any]],
    *,
    owner: str,
    database: str | Path = CACHE_DB_PATH,
) -> list[dict[str, Any]]:
    """Resolve source-free factor objects from the executor's local store."""
    values = [dict(item) for item in entries if isinstance(item, dict)]
    if not values:
        return []
    from server.manager.objects.adapters.factor_source import FactorSourceStore

    store = FactorSourceStore(database=database)
    result: list[dict[str, Any]] = []
    for item in values:
        if item.get("source_code") is not None:
            result.append(item)
            continue
        object_kind = str(item.get("object_kind") or "").strip()
        object_id = str(
            item.get("object_id") or item.get("canonical_family_ref") or ""
        ).strip()
        if object_kind != "factor_source" or not object_id:
            raise ValueError("source-free factor object reference is invalid")
        source_owner, _factor_id = split_owner_qualified_factor_family(object_id)
        if source_owner not in {"public", str(owner or "").strip()}:
            raise PermissionError("factor source object owner does not match Run")
        source = store.source(object_id)
        encoded = source.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if digest != str(item.get("source_sha256") or "").strip().lower():
            raise ValueError("factor source object hash changed")
        if len(encoded) != int(item.get("source_bytes") or -1):
            raise ValueError("factor source object size changed")
        result.append({
            **item,
            "source_code": source,
            "path": portable_source_path(object_id),
        })
    return result


__all__ = [
    "hydrate_source_free_entries",
    "portable_source_path",
    "source_free_context",
    "source_free_manifest",
    "source_transfer_manifest",
]

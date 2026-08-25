"""Source manifests used by an explicit client factor-workspace pull."""

from __future__ import annotations

import hashlib
import os
from typing import Any, cast

from flask import jsonify, request

from server.modules.custom_factors import cf_bp
from server.modules.custom_factors.catalog import _load_factor_family_from_source
from server.services.http_auth import login_required
from server.services.session_runtime import current_user
from tools.data.account_manage import can_view_user_scope
from tools.data.sqlite.factor_source_store import list_factor_sources


def _server_id() -> str:
    return str(os.environ.get("FACTORTESTER_SERVER_ID") or "local").strip() or "local"


def _source_path(kind: str, owner: str, factor_id: str) -> str:
    if kind == "public":
        return f"public_factors/{factor_id}.py"
    if owner == str(current_user() or ""):
        return f"custom_factors/{factor_id}.py"
    owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16]
    return f"remote_factors/{owner_key}/{factor_id}.py"


def _manifest_item(
    *,
    kind: str,
    owner: str,
    factor_id: str,
    factor_name: str,
    source_code: str,
    writable: bool,
    updated_at: float | None,
    chinese_name: str,
    description: str,
    category: str,
) -> dict[str, Any]:
    raw = source_code.encode("utf-8")
    source_hash = hashlib.sha256(raw).hexdigest()
    scope = "public" if kind == "public" else (
        "own" if owner == str(current_user() or "") else "subordinate"
    )
    factor_cls, _ = _load_factor_family_from_source(
        source_code, f"_sync_formula_{factor_id}"
    )
    if factor_cls is None:
        raise ValueError(f"factor family formula cannot be synchronized: {factor_id}")
    family = factor_cls()
    return {
        "source_kind": kind,
        "owner_username": owner,
        "factor_id": factor_id,
        "factor_name": factor_name or factor_id,
        "object_id": f"public:{factor_id}" if kind == "public" else f"{owner}:{factor_id}",
        "path": _source_path(kind, owner, factor_id),
        "scope": scope,
        "writable": bool(writable),
        "family_formula_fingerprint": family.expr.semantic_fingerprint(),
        "source_sha256": source_hash,
        "source_bytes": len(raw),
        "updated_at": updated_at,
        "storage_server_id": _server_id(),
        "content_type": "text/x-python",
        "chinese_name": chinese_name,
        "description": description,
        "category": category,
    }


@cf_bp.route("/api/source-sync/manifest", methods=["GET"])
@login_required
def api_source_sync_manifest():
    """Return visible source metadata without embedding source bytes."""
    username = cast(str, current_user())
    include_subordinates = request.args.get("include_subordinates", "1") == "1"
    items: list[dict[str, Any]] = []

    for row in list_factor_sources("public"):
        factor_id = str(row.get("factor_id") or "").strip()
        source = str(row.get("source_code") or "")
        if factor_id and source:
            items.append(_manifest_item(
                kind="public",
                owner="public",
                factor_id=factor_id,
                factor_name=str(row.get("factor_name") or factor_id),
                source_code=source,
                writable=False,
                updated_at=float(row.get("updated_at") or 0.0),
                chinese_name=str(row.get("chinese_name") or ""),
                description=str(row.get("description") or ""),
                category=str(row.get("category") or ""),
            ))

    for row in list_factor_sources("custom"):
        owner = str(row.get("owner_username") or "").strip()
        factor_id = str(row.get("factor_id") or "").strip()
        source = str(row.get("source_code") or "")
        if not owner or not factor_id or not source:
            continue
        if owner != username and (
            not include_subordinates or not can_view_user_scope(username, owner)
        ):
            continue
        items.append(_manifest_item(
            kind="custom",
            owner=owner,
            factor_id=factor_id,
            factor_name=str(row.get("factor_name") or factor_id),
            source_code=source,
            writable=owner == username,
            updated_at=float(row.get("updated_at") or 0.0),
            chinese_name=str(row.get("chinese_name") or ""),
            description=str(row.get("description") or ""),
            category=str(row.get("category") or ""),
        ))

    items.sort(key=lambda item: (
        str(item.get("scope") or ""),
        str(item.get("owner_username") or ""),
        str(item.get("factor_id") or ""),
    ))
    return jsonify({
        "success": True,
        "schema_version": 1,
        "server_id": _server_id(),
        "principal": username,
        "items": items,
    })


__all__ = ["api_source_sync_manifest"]

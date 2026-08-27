"""Visible factor-source metadata for explicit client workspace pulls."""

from __future__ import annotations

import hashlib
from typing import Any

from server.modules.custom_factors.catalog import _load_factor_family_from_source
from tools.data.account_manage import can_view_user_scope
from tools.data.sqlite.factor_source_store import list_factor_sources


class FactorSourceManifest:
    """Build a source-free, storage-addressed workspace manifest."""

    @staticmethod
    def _source_path(
        kind: str, owner: str, factor_id: str, principal: str,
    ) -> str:
        if kind == "public":
            return f"public_factors/{factor_id}.py"
        if owner == principal:
            return f"custom_factors/{factor_id}.py"
        owner_key = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16]
        return f"remote_factors/{owner_key}/{factor_id}.py"

    @classmethod
    def _item(
        cls,
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
        principal: str,
        server_id: str,
    ) -> dict[str, Any]:
        raw = source_code.encode("utf-8")
        factor_cls, _ = _load_factor_family_from_source(
            source_code, f"_sync_formula_{factor_id}",
        )
        if factor_cls is None:
            raise ValueError(
                f"factor family formula cannot be synchronized: {factor_id}"
            )
        family = factor_cls()
        scope = "public" if kind == "public" else (
            "own" if owner == principal else "subordinate"
        )
        return {
            "source_kind": kind,
            "owner_username": owner,
            "factor_id": factor_id,
            "factor_name": factor_name or factor_id,
            "object_id": (
                f"public:{factor_id}"
                if kind == "public" else f"{owner}:{factor_id}"
            ),
            "path": cls._source_path(kind, owner, factor_id, principal),
            "scope": scope,
            "writable": bool(writable),
            "family_formula_fingerprint": family.expr.semantic_fingerprint(),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "source_bytes": len(raw),
            "updated_at": updated_at,
            "storage_server_id": server_id,
            "content_type": "text/x-python",
            "chinese_name": chinese_name,
            "description": description,
            "category": category,
        }

    def build(
        self,
        principal: str,
        *,
        server_id: str,
        include_subordinates: bool = True,
    ) -> dict[str, Any]:
        owner_principal = str(principal or "").strip()
        storage_server = str(server_id or "local").strip() or "local"
        items: list[dict[str, Any]] = []
        for row in list_factor_sources("public"):
            self._append(
                items, row,
                kind="public", owner="public", principal=owner_principal,
                server_id=storage_server, writable=False,
            )
        for row in list_factor_sources("custom"):
            owner = str(row.get("owner_username") or "").strip()
            if not owner or owner != owner_principal and (
                not include_subordinates
                or not can_view_user_scope(owner_principal, owner)
            ):
                continue
            self._append(
                items, row,
                kind="custom", owner=owner, principal=owner_principal,
                server_id=storage_server, writable=owner == owner_principal,
            )
        items.sort(key=lambda item: (
            str(item.get("scope") or ""),
            str(item.get("owner_username") or ""),
            str(item.get("factor_id") or ""),
        ))
        return {
            "success": True,
            "schema_version": 1,
            "server_id": storage_server,
            "principal": owner_principal,
            "items": items,
        }

    @classmethod
    def _append(
        cls,
        items: list[dict[str, Any]],
        row: dict[str, Any],
        *,
        kind: str,
        owner: str,
        principal: str,
        server_id: str,
        writable: bool,
    ) -> None:
        factor_id = str(row.get("factor_id") or "").strip()
        source = str(row.get("source_code") or "")
        if not factor_id or not source:
            return
        items.append(cls._item(
            kind=kind,
            owner=owner,
            factor_id=factor_id,
            factor_name=str(row.get("factor_name") or factor_id),
            source_code=source,
            writable=writable,
            updated_at=float(row.get("updated_at") or 0.0),
            chinese_name=str(row.get("chinese_name") or ""),
            description=str(row.get("description") or ""),
            category=str(row.get("category") or ""),
            principal=principal,
            server_id=server_id,
        ))


__all__ = ["FactorSourceManifest"]

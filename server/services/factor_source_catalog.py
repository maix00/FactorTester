"""Authorized current and historical FactorFamily source catalog."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from server.modules.custom_factors.catalog import _load_factor_family_from_source
from server.modules.shared.param_meta import serialize_param_meta
from tools.data.account_manage import can_view_user_scope
from tools.data.factor_workspace.storage import (
    load_factor_source,
    load_public_factor_source,
)
from tools.data.sqlite.factor_source_store import get_factor_source_metadata
from tools.data.sqlite.factor_source_versions import (
    list_factor_formula_versions,
    load_factor_formula_version,
)


class FactorSourceCatalog:
    """Keep source authorization and version semantics behind one interface."""

    @staticmethod
    def _kind(value: str) -> str:
        kind = str(value or "").strip().lower()
        if kind not in {"custom", "public"}:
            raise ValueError("源码类型无效")
        return kind

    @staticmethod
    def _source(
        principal: str,
        source_kind: str,
        factor_id: str,
        owner_username: str = "",
    ) -> tuple[str, str]:
        if source_kind == "custom":
            owner = str(owner_username or principal).strip()
            # A principal always may read its own factor sources: the account
            # catalog only decides visibility of *other* users' sources, and
            # it may transiently fail (e.g. control-db fallback to an empty
            # local store) — that must never lock a user out of their own
            # source.  Reading one's own file needs no cross-account grant.
            if not owner or owner == principal:
                return owner or principal, (
                    load_factor_source(owner or principal, factor_id) or ""
                )
            if not can_view_user_scope(principal, owner):
                raise PermissionError("无权查看该用户因子源码")
            return owner, load_factor_source(owner, factor_id) or ""
        return "__public_jobs__", load_public_factor_source(factor_id) or ""

    @staticmethod
    def _detail(
        source_code: str,
        module_name: str,
        metadata: dict[str, str],
    ) -> dict[str, Any]:
        factor_cls, _ = _load_factor_family_from_source(source_code, module_name)
        if factor_cls is None:
            return {
                "source_code": source_code,
                "math_expr": "",
                "chinese_name": metadata.get("chinese_name", ""),
                "description": metadata.get("description", ""),
                "category": metadata.get("category", ""),
                "params": [],
            }
        family = factor_cls()
        return {
            "source_code": source_code,
            "math_expr": getattr(family, "math_expr", "") or "",
            "chinese_name": metadata.get("chinese_name", ""),
            "description": metadata.get("description", ""),
            "category": metadata.get("category", ""),
            "family_formula_fingerprint": family.expr.semantic_fingerprint(),
            "params": [serialize_param_meta(param) for param in family.params],
        }

    def versions(
        self,
        principal: str,
        source_kind: str,
        factor_id: str,
        *,
        owner_username: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        kind = self._kind(source_kind)
        owner, source = self._source(
            principal, kind, factor_id, owner_username,
        )
        if not source:
            raise FileNotFoundError("因子家族当前源码不存在")
        metadata_owner = owner if kind == "custom" else ""
        detail = self._detail(
            source,
            factor_id,
            get_factor_source_metadata(kind, metadata_owner, factor_id),
        )
        current = str(detail.get("family_formula_fingerprint") or "")
        try:
            bounded_limit = min(500, max(1, int(limit)))
        except (TypeError, ValueError) as exc:
            raise ValueError("源码版本数量限制无效") from exc
        values = list_factor_formula_versions(
            kind,
            metadata_owner,
            factor_id,
            current_fingerprint=current,
            limit=bounded_limit,
        )
        return {
            "success": True,
            "available": bool(values),
            "versions": values,
            "current_fingerprint": current,
            "source_kind": kind,
            "factor_id": factor_id,
            "factor_owner_ref": owner,
            "factor_family_alias": factor_id,
        }

    def version(
        self,
        principal: str,
        source_kind: str,
        factor_id: str,
        fingerprint: str,
        *,
        owner_username: str = "",
    ) -> dict[str, Any]:
        kind = self._kind(source_kind)
        owner, current_source = self._source(
            principal, kind, factor_id, owner_username,
        )
        if fingerprint == "current" and not current_source:
            raise FileNotFoundError("因子家族当前源码不存在")
        metadata_owner = owner if kind == "custom" else ""
        metadata = get_factor_source_metadata(kind, metadata_owner, factor_id)
        if fingerprint == "current":
            detail = self._detail(current_source, factor_id, metadata)
            return {
                "success": True,
                **detail,
                "source_sha256": sha256(
                    current_source.encode("utf-8")
                ).hexdigest(),
                "source_kind": kind,
                "factor_id": factor_id,
                "factor_owner_ref": owner,
                "factor_family_alias": factor_id,
                "is_current": True,
            }
        value = load_factor_formula_version(
            kind, metadata_owner, factor_id, fingerprint,
        )
        if value is None or not value.get("source_code"):
            raise FileNotFoundError("因子源码版本不存在")
        return {
            "success": True,
            **value,
            **self._detail(value["source_code"], factor_id, metadata),
            "source_kind": kind,
            "factor_id": factor_id,
            "factor_owner_ref": owner,
            "factor_family_alias": factor_id,
        }

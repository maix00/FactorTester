"""Source-free Factor Library provenance for client Profile bindings."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

_PROJECTION_FIELDS = frozenset({
    "factor_alias",
    "factor_family_alias",
    "factor_family_name",
    "category",
    "params",
    "owner_username",
    "owner_alias",
    "scope_key",
    "product_group",
    "updated_at",
})


class FactorLibraryProvenance:
    """Derive Profile initialization grants from one visible catalog."""

    @staticmethod
    def _factors(catalog: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(item) for item in catalog.get("factors") or []
            if isinstance(item, dict)
            and str(item.get("owner_username") or "").strip()
            not in {"", "__public_jobs__"}
        ]

    def owners(
        self, catalog: dict[str, Any], *, principal: str,
    ) -> dict[str, Any]:
        counts: dict[str, int] = {}
        aliases: dict[str, str] = {}
        for factor in self._factors(catalog):
            owner = str(factor.get("owner_username") or "").strip()
            counts[owner] = counts.get(owner, 0) + 1
            aliases[owner] = str(factor.get("owner_alias") or owner)
        return {
            "success": True,
            "principal": principal,
            "sources": [{
                "owner_ref": owner,
                "owner_alias": aliases[owner],
                "factor_count": counts[owner],
            } for owner in sorted(counts)],
        }

    def projection(
        self,
        catalog: dict[str, Any],
        *,
        principal: str,
        owner_ref: str,
        product_group: str = "",
    ) -> dict[str, Any]:
        owner = str(owner_ref or "").strip()
        scope = str(product_group or "").strip()
        owner_factors = [
            factor for factor in self._factors(catalog)
            if str(factor.get("owner_username") or "") == owner
        ]
        if not owner_factors:
            raise PermissionError("无权查看该用户因子库")
        factors = [
            factor for factor in owner_factors
            if (
                not scope
                or str(
                    factor.get("product_group")
                    or factor.get("scope_key")
                    or ""
                ) == scope
            )
        ]
        projection = {
            "schema_version": 1,
            "principal": principal,
            "owner_ref": owner,
            "factors": [{
                key: item.get(key)
                for key in sorted(_PROJECTION_FIELDS)
                if key in item
            } for item in factors],
        }
        encoded = json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return {
            "success": True,
            "projection": projection,
            "projection_hash": sha256(encoded).hexdigest(),
        }


__all__ = ["FactorLibraryProvenance"]

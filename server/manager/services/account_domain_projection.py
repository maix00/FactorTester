"""Read-only projections of account-domain rows into existing catalog shapes."""

from __future__ import annotations

from typing import Any


def factor_rows_from_sync(sync: object, principal: str) -> list[dict[str, Any]]:
    """Build source-free factor rows from remote parameter-config metadata."""
    try:
        rows = sync.entities(
            principal,
            entity_type="factor_param_config",
            include_shared=False,
        )
    except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("deleted"):
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        entity_id = str(row.get("entity_id") or "")
        scope, separator, family_alias = entity_id.partition(":")
        if not separator:
            family_alias = entity_id
            scope = str(payload.get("scope_key") or "default")
        family_alias = str(
            payload.get("factor_family_alias") or family_alias or "registered"
        ).strip()
        params = payload.get("params_list")
        if not isinstance(params, list):
            params = []
        for index, item in enumerate(params[:512]):
            value = item if isinstance(item, dict) else {}
            factor_alias = str(
                value.get("alias") or value.get("factor_alias") or f"{family_alias}:{index}"
            ).strip()
            if not factor_alias:
                continue
            result.append({
                "factor_alias": factor_alias,
                "factor_family_alias": family_alias,
                "factor_family_name": str(payload.get("name") or family_alias),
                "chinese_name": str(payload.get("chinese_name") or ""),
                "description": str(payload.get("description") or ""),
                "math_expr": str(payload.get("math_expr") or ""),
                "category": str(payload.get("category") or ""),
                "factor_kind": "registered",
                "source": "custom",
                "params": [value],
                "owner_username": str(row.get("principal") or principal),
                "owner_alias": str(row.get("principal") or principal),
                "updated_at": payload.get("updated_at") or row.get("updated_at") or "",
                "product_group": scope,
            })
    return result

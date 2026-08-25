"""Read-only projections of account-domain rows into existing catalog shapes."""

from __future__ import annotations

from typing import Any, Mapping


def factor_rows_from_sync(
    sync: object,
    principal: str,
    *,
    owner_account: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build source-free factor rows from remote parameter-config metadata."""
    try:
        rows = sync.entities(
            principal,
            entity_type="factor_param_config",
            include_shared=False,
            sync=False,
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
        family_name = str(
            payload.get("factor_family_name")
            or payload.get("name")
            or family_alias
        ).strip() or family_alias
        # Older account migration stored the owner username in the family
        # ``name`` field.  A username is not a family name; keep the stable
        # family alias as the display fallback instead of exposing the legacy
        # identity on every family row.
        identity_values = {
            str(item).strip()
            for item in (
                row.get("principal"), principal, payload.get("id"),
                payload.get("scope_user_id"),
            )
            if str(item or "").strip()
        }
        if family_name in identity_values or _looks_like_username(family_name):
            family_name = family_alias
        factors = payload.get("resolved_factors")
        if not isinstance(factors, list):
            factors = []
        for item in factors[:512]:
            value = item if isinstance(item, dict) else {}
            factor_alias = str(value.get("factor_alias") or "").strip()
            if not factor_alias:
                continue
            result.append({
                "factor_alias": factor_alias,
                "factor_family_alias": str(
                    value.get("factor_family_alias") or family_alias
                ),
                "factor_family_name": str(
                    value.get("factor_family_name") or family_name
                ),
                "factor_owner_ref": str(
                    value.get("factor_owner_ref")
                    or payload.get("factor_owner_ref")
                    or row.get("principal")
                    or principal
                ),
                "chinese_name": str(
                    value.get("chinese_name") or payload.get("chinese_name") or ""
                ),
                "description": str(
                    value.get("description") or payload.get("description") or ""
                ),
                "math_expr": str(
                    value.get("math_expr") or payload.get("math_expr") or ""
                ),
                "category": str(
                    value.get("category") or payload.get("category") or ""
                ),
                "factor_kind": str(value.get("factor_kind") or "registered"),
                "source": str(value.get("source") or "custom"),
                "params": list(value.get("params") or value.get("factor_params") or []),
                "factor_params": list(
                    value.get("factor_params") or value.get("params") or []
                ),
                "owner_username": str(row.get("principal") or principal),
                "owner_alias": _owner_alias(
                    str(row.get("principal") or principal),
                    principal,
                    owner_account,
                ),
                "owner_organization_id": str(
                    (owner_account or {}).get("organization_id") or ""
                ),
                "owner_organization_name": str(
                    (owner_account or {}).get("organization_name") or ""
                ),
                "updated_at": payload.get("updated_at") or row.get("updated_at") or "",
                "product_group": scope,
                **({
                    "family_formula_fingerprint": str(
                        value["family_formula_fingerprint"]
                    )
                } if value.get("family_formula_fingerprint") else {}),
                **({
                    "self_formula_fingerprint": str(
                        value["self_formula_fingerprint"]
                    )
                } if value.get("self_formula_fingerprint") else {}),
            })
    return result


def _owner_alias(
    owner: str,
    principal: str,
    owner_account: Mapping[str, Any] | None,
) -> str:
    if owner == "__public__":
        return "公共因子库"
    if owner == principal and owner_account is not None:
        alias = str(owner_account.get("alias") or "").strip()
        if alias:
            return alias
    parts = owner.split("@")
    if len(parts) == 3 and parts[2].isdigit():
        return parts[1]
    return owner


def _looks_like_username(value: str) -> bool:
    clean = str(value or "").strip()
    if clean.isdigit():
        return True
    parts = clean.split("@")
    return len(parts) == 3 and parts[0] and parts[1] and parts[2].isdigit()

"""Materialize stable, source-free factor rows for account-domain sync."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


_FACTOR_KEYS = (
    "factor_alias", "factor_family_alias", "factor_family_name",
    "factor_owner_ref", "family_formula_fingerprint",
    "self_formula_fingerprint",
    "params", "factor_params", "chinese_name", "description", "math_expr",
    "category", "factor_kind", "source", "owner_username", "owner_alias",
    "owner_organization_id", "owner_organization_name", "updated_at",
    "scope_key", "product_group",
)


def materialized_factor_configs(owner: str) -> list[tuple[str, dict[str, Any]]]:
    """Return local configs enriched with aliases resolved by their source family."""
    from server.modules.custom_factors.factor_library_service import (
        build_factor_library_overview,
    )
    from tools.data.account_manage import (
        get_account,
        list_factor_param_config_aliases,
        list_factor_param_config_scopes,
        load_factor_param_config,
    )

    account = get_account(owner) or {"username": owner}
    overview = build_factor_library_overview(
        owner,
        include_subordinates=False,
        account=account,
        include_scope_catalog=False,
    )
    resolved: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in overview.get("factors") or []:
        if not isinstance(item, dict):
            continue
        alias = str(item.get("factor_alias") or "").strip()
        family = str(item.get("factor_family_alias") or "").strip()
        scope = str(
            item.get("scope_key") or item.get("product_group") or "default"
        ).strip() or "default"
        if alias and family:
            resolved[(scope, family)].append({
                key: item[key] for key in _FACTOR_KEYS if item.get(key) not in (None, "")
            })

    result: list[tuple[str, dict[str, Any]]] = []
    for scope in list_factor_param_config_scopes(owner):
        for family in list_factor_param_config_aliases(owner, scope):
            value = load_factor_param_config(owner, family, scope)
            if not isinstance(value, dict):
                continue
            payload = dict(value)
            payload["factor_family_alias"] = family
            payload["resolved_factors"] = resolved.get((scope, family), [])
            result.append((f"{scope}:{family}", payload))
    return result

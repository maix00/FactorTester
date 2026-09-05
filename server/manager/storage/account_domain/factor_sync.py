"""Materialize stable, source-free factor rows for account-domain sync."""

from __future__ import annotations

from typing import Any


_FACTOR_KEYS = (
    "schema_version", "ref", "alias", "owner_ref", "identity",
    "factor_ref",
    "factor_alias", "factor_family_alias", "factor_family_name",
    "factor_owner_ref", "family_formula_fingerprint",
    "self_formula_fingerprint",
    "params", "factor_params", "parameter_definitions", "chinese_name",
    "description", "math_expr", "resolved_math_expr", "factor_dependencies",
    "category", "factor_kind", "source", "owner_username", "owner_alias",
    "owner_organization_id", "owner_organization_name", "updated_at",
    "scope_key", "product_group",
)


def materialized_factor_configs(owner: str, *, existing: list[dict[str, Any]] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Freeze changed authoring configurations; reuse persisted frozen rows otherwise."""
    from server.modules.custom_factors.factor_library_service import build_factor_library_config_factors
    from tools.data.account_manage import (
        get_account, list_factor_param_config_aliases, list_factor_param_config_scopes,
        load_factor_param_config,
    )
    account = get_account(owner) or {"username": owner}
    prior = {row["entity_id"]: row for row in existing or []}
    result = []
    for scope in list_factor_param_config_scopes(owner):
        for family in list_factor_param_config_aliases(owner, scope):
            identifier = f"{scope}:{family}"
            previous_row = prior.get(identifier)
            previous = (previous_row or {}).get("payload") or {}
            if previous_row and previous_row.get("deleted"):
                # An old authored copy is not a request to resurrect a deletion.
                continue
            if (isinstance(previous.get("resolved_factors"), list)
                    and len(previous["resolved_factors"]) >= len(previous.get("params_list") or [])):
                # The write hook replaces this payload with a raw draft before
                # a real authoring edit. On restart, the durable frozen mirror
                # wins over a stale authored copy from another Manager.
                result.append((identifier, previous))
                continue
            config = load_factor_param_config(owner, family, scope)
            if not isinstance(config, dict):
                continue
            try:
                factors = build_factor_library_config_factors(owner, account, family, config)
            except (ImportError, AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                # Missing source/dependency is a deferred materialization, not
                # a deletion or an empty authoritative factor registration.
                continue
            if len(factors) < len(config.get("params_list") or []):
                continue
            resolved = [{key: item[key] for key in _FACTOR_KEYS if item.get(key) not in (None, "")}
                        for item in factors if isinstance(item, dict)]
            from .payloads import public_payload
            payload = public_payload({**config, "schema_version": 2, "factor_family_alias": family,
                                      "resolved_factors": resolved})
            result.append((identifier, payload))
    return result

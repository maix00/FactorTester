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


def materialized_factor_configs(owner: str, *, existing: list[dict[str, Any]] | None = None, fingerprints: dict[str, str] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Freeze changed authoring configurations; reuse persisted frozen rows otherwise."""
    import hashlib
    import json
    from server.modules.custom_factors.factor_library_service import build_factor_library_config_factors
    from tools.data.account_manage import (
        get_account, list_factor_param_config_aliases, list_factor_param_config_scopes,
        load_factor_param_config,
    )
    account = get_account(owner) or {"username": owner}
    prior = {row["entity_id"]: row.get("payload") or {} for row in existing or [] if not row.get("deleted")}
    result = []
    for scope in list_factor_param_config_scopes(owner):
        for family in list_factor_param_config_aliases(owner, scope):
            config = load_factor_param_config(owner, family, scope)
            if not isinstance(config, dict):
                continue
            identifier = f"{scope}:{family}"
            digest = hashlib.sha256(json.dumps(
                {key: value for key, value in config.items() if key != "updated_at"},
                sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode()).hexdigest()
            previous = prior.get(identifier, {})
            if (fingerprints is not None and fingerprints.get(identifier) == digest
                    and isinstance(previous.get("resolved_factors"), list)):
                continue
            comparable = {key: previous.get(key) for key in config if key != "updated_at"}
            if comparable == {key: value for key, value in config.items() if key != "updated_at"} and isinstance(previous.get("resolved_factors"), list):
                result.append((identifier, previous))
                if fingerprints is not None:
                    fingerprints[identifier] = digest
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
            payload = public_payload({**config, "factor_family_alias": family,
                                      "resolved_factors": resolved})
            result.append((identifier, payload))
            if fingerprints is not None:
                fingerprints[identifier] = digest
    return result

"""Materialize stable, source-free factor rows for account-domain sync."""

from __future__ import annotations

from typing import Any

from server.modules.shared.factor_preview_latex import RESOLVED_MATH_EXPR_VERSION


_FACTOR_KEYS = (
    "schema_version", "ref", "alias", "owner_ref", "identity",
    "factor_ref",
    "factor_alias", "factor_family_alias", "factor_family_name",
    "factor_owner_ref", "family_formula_fingerprint",
    "self_formula_fingerprint",
    "params", "factor_params", "chinese_name",
    "description", "math_expr", "resolved_math_expr_version", "factor_dependencies",
    "category", "factor_kind", "source", "owner_username", "owner_alias",
    "owner_organization_id", "owner_organization_name", "updated_at",
    "scope_key", "product_group",
)

# 依赖记录本身不再携带自己的 factor_dependencies（已在扁平化时递归走完），
# 否则扁平后的每个记录又会把整棵子树重新嵌进去，深链下再次指数膨胀。
_DEPENDENCY_KEYS = tuple(key for key in _FACTOR_KEYS if key != "factor_dependencies")


def _flatten_dependencies(dependencies: Any) -> list[dict[str, Any]]:
    """把（可能嵌套的）factor_dependencies 扁平化，并按 ref 去重。

    冻结依赖是递归的：每个记录再嵌自己的依赖，深链（如
    TsHistCmp → *DayScope → SgChgDurDay → SgChgPct → …）下同一子记录被反复
    展开，序列化后超过账户域 512KiB 载荷上限。这里每个冻结记录只保留一次。
    """
    flat: dict[str, dict[str, Any]] = {}
    stack = list(dependencies or [])
    while stack:
        record = stack.pop(0)
        if not isinstance(record, dict):
            continue
        ref = record.get("ref")
        if ref:
            flat.setdefault(ref, {
                key: record[key] for key in _DEPENDENCY_KEYS if record.get(key) not in (None, "")
            })
        stack.extend(record.get("factor_dependencies") or [])
    return list(flat.values())


def _resolved_factor_rows(factors: Any) -> list[dict[str, Any]]:
    """账户域载荷里的 resolved_factors：依赖扁平去重后的记录。"""
    rows: list[dict[str, Any]] = []
    for item in factors:
        if not isinstance(item, dict):
            continue
        record = {key: item[key] for key in _FACTOR_KEYS if item.get(key) not in (None, "")}
        if "factor_dependencies" in record:
            record["factor_dependencies"] = _flatten_dependencies(record["factor_dependencies"])
        rows.append(record)
    return rows


def materialized_factor_configs(owner: str, *, existing: list[dict[str, Any]] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Freeze changed authoring configurations; reuse persisted frozen rows otherwise.

    A frozen row can outlive its editable authoring config.  When the preview
    renderer changes, rebuild that retained row from its persisted parameter
    values and frozen dependency metadata instead of leaving an old formula in
    the catalog indefinitely.
    """
    from server.modules.custom_factors.factor_library_service import build_factor_library_config_factors
    from tools.data.account_manage import (
        get_account, list_factor_param_config_aliases, list_factor_param_config_scopes,
        load_factor_param_config,
    )
    account = get_account(owner) or {"username": owner}
    prior = {row["entity_id"]: row for row in existing or []}
    from .payloads import public_payload

    def refresh_stale_row(identifier: str, previous_row: dict[str, Any], previous: dict[str, Any]):
        """Re-materialize an old frozen row even after authoring is removed."""
        if previous_row.get("deleted"):
            return None
        previous_factors = previous.get("resolved_factors")
        params_list = previous.get("params_list")
        if not isinstance(previous_factors, list) or not isinstance(params_list, list):
            return None
        if not previous_factors or all(
            isinstance(item, dict)
            and str(item.get("resolved_math_expr") or "").strip()
            and item.get("resolved_math_expr_version") == RESOLVED_MATH_EXPR_VERSION
            for item in previous_factors
        ):
            return None
        family = str(
            previous.get("factor_family_alias")
            or identifier.rsplit(":", 1)[-1]
        ).strip()
        if not family:
            return None
        scope_key = str(
            previous.get("scope_key")
            or previous.get("product_group")
            or identifier.split(":", 1)[0]
            or "default"
        ).strip()
        synthetic_config = {
            "params_list": params_list,
            "metadata": previous.get("metadata")
            if isinstance(previous.get("metadata"), dict) else {},
            "scope_key": scope_key,
            "product_group": str(previous.get("product_group") or scope_key),
        }
        try:
            factors = build_factor_library_config_factors(
                owner, account, family, synthetic_config,
            )
        except (ImportError, AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            return None
        if len(factors) < len(params_list):
            return None
        resolved = _resolved_factor_rows(factors)
        if len(resolved) < len(params_list):
            return None
        return public_payload({
            **previous,
            "schema_version": 2,
            "factor_family_alias": family,
            "resolved_factors": resolved,
        })

    result = []
    emitted: set[str] = set()
    for scope in list_factor_param_config_scopes(owner):
        for family in list_factor_param_config_aliases(owner, scope):
            identifier = f"{scope}:{family}"
            emitted.add(identifier)
            previous_row = prior.get(identifier)
            previous = (previous_row or {}).get("payload") or {}
            if previous_row and previous_row.get("deleted"):
                # An old authored copy is not a request to resurrect a deletion.
                continue
            previous_factors = previous.get("resolved_factors")
            has_resolved_formulas = (
                isinstance(previous_factors, list)
                and all(
                    isinstance(item, dict)
                    and item.get("resolved_math_expr_version")
                    == RESOLVED_MATH_EXPR_VERSION
                    and item.get("identity")
                    for item in previous_factors
                )
            )
            if (has_resolved_formulas
                    and len(previous_factors) >= len(previous.get("params_list") or [])):
                # The write hook replaces this payload with a raw draft before
                # a real authoring edit. On restart, the durable frozen mirror
                # wins over a stale authored copy from another Manager.
                result.append((identifier, previous))
                continue
            config = load_factor_param_config(owner, family, scope)
            if not isinstance(config, dict):
                if previous_factors:
                    refreshed = refresh_stale_row(identifier, previous_row or {}, previous)
                    result.append((identifier, refreshed or previous))
                continue
            try:
                factors = build_factor_library_config_factors(owner, account, family, config)
            except (ImportError, AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                # Missing source/dependency is a deferred materialization, not
                # a deletion or an empty authoritative factor registration.
                if previous_factors:
                    result.append((identifier, previous))
                continue
            if len(factors) < len(config.get("params_list") or []):
                if previous_factors:
                    result.append((identifier, previous))
                continue
            resolved = _resolved_factor_rows(factors)
            payload = public_payload({**config, "schema_version": 2, "factor_family_alias": family,
                                      "resolved_factors": resolved})
            result.append((identifier, payload))
    # Preserve and, when possible, refresh retained frozen rows whose editable
    # authoring config is no longer listed in the account store.
    for identifier, previous_row in prior.items():
        if identifier in emitted or not isinstance(previous_row, dict):
            continue
        previous = previous_row.get("payload") or {}
        if not isinstance(previous, dict):
            continue
        refreshed = refresh_stale_row(identifier, previous_row, previous)
        if refreshed is not None:
            result.append((identifier, refreshed))
    return result

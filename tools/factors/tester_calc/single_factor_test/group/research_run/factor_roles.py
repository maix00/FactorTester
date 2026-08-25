"""Resolve primary and role-bound factors from one frozen RunSpec."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tools.factors.formula_identity import require_frozen_factor


def _factor_source_alias(alias: str, data: dict) -> str:
    """Restore the source owner for a frozen concrete factor alias.

    The editable group keeps the short display alias (for example
    ``CA|$F:1m``), while ``shared.factors`` carries the immutable source
    owner.  Runtime resolution must use both pieces: otherwise a delegated
    factor is incorrectly looked up in the executor user's own library.
    """
    alias = str(alias or "").strip()
    if not alias or not isinstance(data, Mapping):
        return alias
    factors = data.get("factors")
    if not isinstance(factors, list):
        return alias
    item = next(
        (
            value for value in factors
            if isinstance(value, Mapping)
            and str(value.get("alias") or "").strip() == alias
        ),
        None,
    )
    if item is None:
        return alias

    try:
        frozen = require_frozen_factor(item)
    except (TypeError, ValueError):
        return alias
    family_alias = str(frozen["identity"]["family_alias"]).strip()
    owner_ref = str(frozen["owner_ref"]).strip()
    if not family_alias or not owner_ref or ":" in family_alias:
        return alias
    family_ref = f"{owner_ref}:{family_alias}"
    family_alias_in_alias = alias.split("|", 1)[0]
    return family_ref + alias[len(family_alias_in_alias):]


def resolve_factor(
    alias: str,
    *,
    data: dict,
    page_factors: dict,
    page_uuid: str,
    username: str,
) -> Any:
    factor = page_factors.get(alias)
    if factor is None:
        from server.services.external_factor_artifacts import factor_by_alias

        factor = factor_by_alias(data.get("external_factor_artifacts"), alias)
    if factor is None:
        from server.services.factor_registry import factor_from_alias

        try:
            factor = factor_from_alias(
                _factor_source_alias(alias, data),
                username=username,
                page_uuid=page_uuid,
            )
        except Exception as exc:
            raise ValueError(
                f"未找到因子 {alias}。仅允许从当前用户可访问的公共因子家族"
                "或当前用户自己的因子家族解析。"
            ) from exc
    return factor


def resolve_factor_ref(
    factor_ref: str,
    *,
    data: dict,
    page_factors: dict,
    page_uuid: str,
    username: str,
) -> Any:
    """Hydrate one frozen factor identity into the runtime Factor object."""

    wanted = str(factor_ref or "").strip()
    factor = page_factors.get(wanted)
    if factor is not None:
        return factor
    descriptor = None
    for item in data.get("factors") or ():
        try:
            frozen = require_frozen_factor(item)
        except (TypeError, ValueError):
            continue
        if frozen["ref"] == wanted:
            descriptor = frozen
            break
    if descriptor is None:
        raise ValueError(f"未找到因子引用 {wanted}")
    alias = str(descriptor["alias"]).strip()
    if not alias:
        raise ValueError(f"冻结因子描述缺少显示别名: {wanted}")
    return resolve_factor(
        alias, data=data, page_factors=page_factors,
        page_uuid=page_uuid, username=username,
    )


def resolve_factor_role_bindings(
    raw: Any,
    *,
    data: dict,
    page_factors: dict,
    page_uuid: str,
    username: str,
) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("factor_role_bindings must be a role-to-factor mapping")
    result: dict[str, Any] = {}
    for role, binding in raw.items():
        if isinstance(binding, Mapping):
            factor_ref = str(
                binding.get("factor_ref") or binding.get("target_ref") or ""
            ).strip()
        elif isinstance(binding, str):
            factor_ref = binding.strip()
        else:
            result[str(role)] = binding
            continue
        if not factor_ref:
            raise ValueError(f"factor role {role!r} is missing factor_ref")
        result[str(role)] = resolve_factor_ref(
            factor_ref,
            data=data,
            page_factors=page_factors,
            page_uuid=page_uuid,
            username=username,
        )
    return result

"""Resolve primary and role-bound factors from one frozen RunSpec."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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
            factor = factor_from_alias(alias, username=username, page_uuid=page_uuid)
        except Exception as exc:
            raise ValueError(
                f"未找到因子 {alias}。仅允许从当前用户可访问的公共因子家族"
                "或当前用户自己的因子家族解析。"
            ) from exc
    return factor


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
            alias = str(
                binding.get("factorAlias")
                or binding.get("factor_alias")
                or binding.get("alias")
                or ""
            ).strip()
        elif isinstance(binding, str):
            alias = binding.strip()
        else:
            result[str(role)] = binding
            continue
        if not alias:
            raise ValueError(f"factor role {role!r} is missing factor alias")
        result[str(role)] = resolve_factor(
            alias,
            data=data,
            page_factors=page_factors,
            page_uuid=page_uuid,
            username=username,
        )
    return result

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
    from server.modules.shared.run_spec_resolution.factors import RunFactorResolver

    try:
        return RunFactorResolver(
            owner=username,
            frozen_factors=data.get("factors"),
            external_factor_artifacts=data.get("external_factor_artifacts"),
            page_factors=page_factors,
            page_uuid=page_uuid,
        ).resolve(alias=alias)
    except Exception as exc:
        raise ValueError(
            f"未找到因子 {alias}。仅允许从运行配置冻结因子或可访问因子源解析。"
        ) from exc


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
    from server.modules.shared.run_spec_resolution.factors import RunFactorResolver

    try:
        return RunFactorResolver(
            owner=username,
            frozen_factors=data.get("factors"),
            external_factor_artifacts=data.get("external_factor_artifacts"),
            page_factors=page_factors,
            page_uuid=page_uuid,
        ).resolve(factor_ref=wanted)
    except Exception as exc:
        raise ValueError(f"未找到因子引用 {wanted}") from exc


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

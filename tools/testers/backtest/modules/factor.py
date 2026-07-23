"""FactorModule — declares the `factor` field every strategy's signal
generation reads from. Field declaration only; FactorSignalModule (this
package's factor_signal.py) owns the Flows that actually use it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


class FactorModule(ExecutableModule):
    key: ClassVar[str] = "factor"
    label: ClassVar[str] = "因子"
    order: ClassVar[int] = 20

    # A resolved ``Factor`` is itself a ``FactorExpr`` and retains its alias
    # and result-cache lifecycle. The runtime must not replace it with an
    # execution-specific wrapper.
    factor: ClassVar[FieldRef[Any]] = FieldRef("factor")
    factor_candidates: ClassVar[FieldRef[list[Any]]] = FieldRef("factor_candidates")
    factor_role_bindings: ClassVar[FieldRef[Any]] = FieldRef("factor_role_bindings")
    factor_role_values: ClassVar[FieldRef[Any]] = FieldRef("factor_role_values")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "factor_candidates": FieldDefinition(
            public=True, label="因子候选", default=[], control_template="custom", tab="factor",
            chip_template="因子候选: {value}", tab_label="因子执行", tab_order=20,
            help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场因子。",
            serialization={
                "kind": "factor_candidate_list",
                "display_order": 10,
                "item_kind": "factor",
                "shared_page_field": "factor_candidates",
                "selection_field": "factor",
                "factor_library_source": "user_factor_library_overview",
                "fallback_policy": (
                    "copy_page_candidates",
                    "load_factor_library_when_page_empty",
                ),
                "id_keys": ("alias", "name", "factor_alias"),
                "label_keys": ("alias", "name", "label"),
                "mutation_scope": {
                    "page": "page_candidates_only",
                    "module": "module_candidates_only",
                },
            },
        ),
        "factor": FieldDefinition(
            public=True, label="因子", default="", control_template="select", tab="factor",
            chip_template="因子: {value}", tab_label="因子执行", tab_order=20,
            info_overlay={"type": "factor_info"},
            serialization={
                "kind": "factor_selection",
                "display_order": 20,
                "candidate_field": "factor_candidates",
                "shared_page_field": "factor",
                "id_keys": ("alias", "name", "factor_alias"),
                "label_keys": ("alias", "name", "label"),
            },
        ),
        "factor_role_bindings": FieldDefinition(
            public=True,
            label="因子角色",
            default={},
            control_template="factor_role_bindings",
            tab="factor",
            chip_template="因子角色: {value}",
            tab_label="因子执行",
            tab_order=20,
            help_text="按策略意图绑定 ranking、entry、exit；未绑定角色显式使用主因子。",
            serialization={
                "kind": "factor_role_bindings",
                "candidate_field": "factor_candidates",
                "allowed_roles": ("ranking", "entry", "exit"),
                "roles_by_strategy_kind": {
                    "group": ("ranking",),
                    "threshold": ("entry", "exit"),
                },
            },
        ),
        "factor_role_values": FieldDefinition(
            public=False,
            display_value_kind="factor_role_values",
        ),
    }


def factor_runtime_key(factor: Any) -> Any:
    """Stable key for sharing one runtime factor calculation.

    Raw factor objects default to identity because factor instances may carry
    mutable caches/state. Adapter wrappers can expose a semantic key when they
    are merely binding the same underlying factor to the same product universe.
    """
    custom_key = getattr(factor, "backtest_factor_cache_key", None)
    if callable(custom_key):
        return custom_key()
    if custom_key is not None:
        return custom_key
    return ("object", id(factor))


def factor_role_bindings_for(config: Any) -> dict[str, Any]:
    raw = config.get(FactorModule.factor_role_bindings, {}) or {}
    if not isinstance(raw, Mapping):
        raise ValueError("factor_role_bindings must be a role-to-factor mapping")
    allowed = {"ranking", "entry", "exit"}
    unknown = sorted(str(role) for role in raw if str(role) not in allowed)
    if unknown:
        raise ValueError(f"unsupported factor roles: {', '.join(unknown)}")
    return {str(role): factor for role, factor in raw.items() if factor not in (None, "")}


def factors_for_config(config: Any) -> tuple[Any, ...]:
    factors = [config.get(FactorModule.factor), *factor_role_bindings_for(config).values()]
    unique: list[Any] = []
    for factor in factors:
        if factor is not None and all(factor is not existing for existing in unique):
            unique.append(factor)
    return tuple(unique)

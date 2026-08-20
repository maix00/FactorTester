"""FactorModule — declares the `factor` field every strategy's signal
generation reads from. Field declaration only; FactorSignalModule (this
package's factor_signal.py) owns the Flows that actually use it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.factor_authoring_contract import factor_identity_serialization


class FactorModule(ExecutableModule):
    key: ClassVar[str] = "factor"
    label: ClassVar[str] = "因子"
    order: ClassVar[int] = 20

    # A resolved ``Factor`` is itself a ``FactorExpr`` and retains its alias
    # and result-cache lifecycle. The runtime must not replace it with an
    # execution-specific wrapper.
    factor: ClassVar[FieldRef[Any]] = FieldRef("factor")
    factor_candidates: ClassVar[FieldRef[list[Any]]] = FieldRef("factor_candidates")
    factor_source_selections: ClassVar[FieldRef[list[Any]]] = FieldRef(
        "factor_source_selections"
    )
    factor_set_selections: ClassVar[FieldRef[list[Any]]] = FieldRef("factor_set_selections")
    factor_role_bindings: ClassVar[FieldRef[Any]] = FieldRef("factor_role_bindings")
    factor_role_values: ClassVar[FieldRef[Any]] = FieldRef("factor_role_values")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "factor_candidates": FieldDefinition(
            public=True, label="因子候选", default=[], editor="custom", tab="factor",
            chip_template="因子候选: {value}", tab_label="因子执行", tab_order=20,
            tab_default_mount_points=("local-settings",),
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场因子。",
            serialization={
                "kind": "factor_candidate_list",
                "display_order": 10,
                "item_kind": "factor",
                "shared_page_field": "factor_candidates",
                "selection_field": "factor_candidates",
                **factor_identity_serialization(),
                "factor_library_source": "user_factor_library_overview",
                "fallback_policy": (
                    "copy_page_candidates",
                    "load_factor_library_when_page_empty",
                ),
                "mutation_scope": {
                    "page": "page_candidates_only",
                    "module": "module_candidates_only",
                },
            },
        ),
        "factor_source_selections": FieldDefinition(
            public=True, label="因子来源", default=[], editor="custom", tab="factor",
            chip_template="因子: {value}", tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="从可见因子库多选直接来源；因子候选由直接因子与因子集合展开得到。",
            serialization={
                "kind": "factor_source_selection_list",
                "display_order": 12,
                "multi": True,
                "candidate_field": "factor_candidates",
                "set_source_field": "factor_set_selections",
                "selection_field": "factor_candidates",
                "source_kind": "factor",
                "catalog_source": "visible_factor_catalog",
                "allow_inline_create": True,
                **factor_identity_serialization(),
            },
        ),
        "factor_set_selections": FieldDefinition(
            public=True, label="因子集合来源", default=[], editor="custom",
            tab="factor", chip_template="因子集合: {value}",
            tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="选择集合后展开为具体因子候选；运行时同时冻结集合身份与成员因子",
            serialization={
                "kind": "factor_set_selection_list",
                "display_order": 15,
                "multi": True,
                "candidate_field": "factor_candidates",
                "selection_field": "factor_candidates",
                "catalog_endpoint": "/api/catalog/factor-sets",
                "detail_endpoint": "/api/catalog/factor-sets/detail",
                "descriptor_endpoint": "/api/catalog/factor-sets/descriptor",
                "native_catalog_action": "catalog",
                "native_detail_action": "members",
                "native_descriptor_action": "descriptor",
                "native_run_input_action": "run-input",
            },
        ),
        "factor": FieldDefinition(
            # Runtime-only.  The authoring surface persists stable
            # ``factor_candidate_refs`` on each strategy; the compiler
            # resolves those references to Factor objects before execution.
            public=False, label="因子", default="", editor="select", tab="factor",
            chip_template="因子: {value}", tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="从已加载的因子候选中选择本次测试使用的因子；回测使用单个因子。",
            info_overlay={"type": "factor_info"},
            serialization={
                "kind": "factor_selection",
                "display_order": 20,
                "candidate_field": "factor_candidates",
                "shared_page_field": "factor",
                "outer_selection_mode": "automatic_primary",
                "outer_selection_label": "选中因子",
                "resolution": {
                    "kind": "automatic",
                    "source": "factor_candidates",
                    "resolver": "primary_item",
                    "editable": False,
                },
                **factor_identity_serialization(),
            },
        ),
        "factor_role_bindings": FieldDefinition(
            public=True,
            label="因子角色",
            default={},
            editor="factor_role_bindings",
            tab="factor",
            chip_template="因子角色: {value}",
            tab_label="因子执行",
            tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True,
            help_text=(
                "仅在已有至少两个可绑定因子候选时显示；按策略意图绑定"
                " ranking、screen、entry、exit、sizing，未绑定角色使用主因子。"
            ),
            serialization={
                "kind": "factor_role_bindings",
                "candidate_field": "factor_candidates",
                "visible_when": {"min_items": {"factor_candidates": 2}},
                "allowed_roles": ("ranking", "screen", "entry", "exit", "sizing"),
                "roles_by_strategy_kind": {
                    "group": ("ranking", "screen", "sizing"),
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
    allowed = {"ranking", "screen", "entry", "exit", "sizing"}
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

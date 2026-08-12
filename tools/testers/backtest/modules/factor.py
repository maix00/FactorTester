"""FactorModule — declares the `factor` field every strategy's signal
generation reads from. Field declaration only; FactorSignalModule (this
package's factor_signal.py) owns the Flows that actually use it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.run_input_contracts import factor_source_content_options


class FactorModule(ExecutableModule):
    key: ClassVar[str] = "factor"
    label: ClassVar[str] = "因子"
    order: ClassVar[int] = 20

    # A resolved ``Factor`` is itself a ``FactorExpr`` and retains its alias
    # and result-cache lifecycle. The runtime must not replace it with an
    # execution-specific wrapper.
    factor: ClassVar[FieldRef[Any]] = FieldRef("factor")
    factor_owner_ref: ClassVar[FieldRef[str]] = FieldRef("factor_owner_ref")
    factor_git_commit: ClassVar[FieldRef[str]] = FieldRef("factor_git_commit")
    factor_family_ref: ClassVar[FieldRef[str]] = FieldRef("factor_family_ref")
    factor_params: ClassVar[FieldRef[dict[str, Any]]] = FieldRef("factor_params")
    factor_candidates: ClassVar[FieldRef[list[Any]]] = FieldRef("factor_candidates")
    factor_set_selections: ClassVar[FieldRef[list[Any]]] = FieldRef("factor_set_selections")
    factor_role_bindings: ClassVar[FieldRef[Any]] = FieldRef("factor_role_bindings")
    factor_role_values: ClassVar[FieldRef[Any]] = FieldRef("factor_role_values")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "factor_owner_ref": FieldDefinition(
            public=True, label="因子所有者", default="", control_template="custom",
            tab="factor", chip_template="因子所有者: {value}",
            tab_label="因子执行", tab_order=20,
            tab_default_mount_points=("local-settings",),
            tab_content_adapter="factor_selection",
            tab_content_options=factor_source_content_options(),
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="选择用户或 Profile 已注册的因子工作区",
            serialization={
                "kind": "factor_owner_selection", "display_order": 1,
                "catalog_command": "client catalog owner list",
            },
        ),
        "factor_git_commit": FieldDefinition(
            public=True, label="Git commit", default="", control_template="custom",
            tab="factor", chip_template="Git commit: {value}",
            tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="冻结所选所有者因子工作区的精确提交",
            serialization={
                "kind": "factor_revision_selection", "display_order": 2,
                "owner_field": "factor_owner_ref",
                "catalog_command": "client catalog revision list",
            },
        ),
        "factor_family_ref": FieldDefinition(
            public=True, label="因子家族", default="", control_template="custom",
            tab="factor", chip_template="因子家族: {value}",
            tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="只显示所选 owner 与 Git commit 中可加载的因子家族",
            serialization={
                "kind": "factor_family_selection", "display_order": 3,
                "owner_field": "factor_owner_ref",
                "revision_field": "factor_git_commit",
                "catalog_command": "client catalog family list",
            },
        ),
        "factor_params": FieldDefinition(
            public=True, label="因子参数", default={}, control_template="custom",
            tab="factor", tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="按因子家族参数定义生成一个冻结的具体因子候选",
            serialization={
                "kind": "factor_parameter_values", "display_order": 4,
                "family_field": "factor_family_ref",
                "candidate_field": "factor_candidates",
                "catalog_command": "client catalog factor instantiate",
            },
        ),
        "factor_candidates": FieldDefinition(
            public=True, label="因子候选", default=[], control_template="custom", tab="factor",
            chip_template="因子候选: {value}", tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场因子。",
            serialization={
                "kind": "factor_candidate_list",
                "display_order": 10,
                "item_kind": "factor",
                "owner_field": "factor_owner_ref",
                "revision_field": "factor_git_commit",
                "family_field": "factor_family_ref",
                "params_field": "factor_params",
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
        "factor_set_selections": FieldDefinition(
            public=True, label="因子集合来源", default=[], control_template="custom",
            tab="factor", chip_template="因子集合: {value}",
            tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=True,
            execution_policy="authoring_only",
            help_text="选择集合后展开为具体因子候选；运行时同时冻结集合身份与成员因子",
            serialization={
                "kind": "factor_set_selection_list",
                "display_order": 15,
                "multi": True,
                "candidate_field": "factor_candidates",
                "selection_field": "factor",
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
            public=True, label="因子", default="", control_template="select", tab="factor",
            chip_template="因子: {value}", tab_label="因子执行", tab_order=20,
            tab_content_adapter="factor_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
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
            tab_content_adapter="factor_selection",
            help_text="按策略意图绑定 ranking、screen、entry、exit、sizing；未绑定角色显式使用主因子。",
            serialization={
                "kind": "factor_role_bindings",
                "candidate_field": "factor_candidates",
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

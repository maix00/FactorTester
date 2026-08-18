"""Shared factor execution setting registrations.

Used by: single_factor_page, group_test, ic_test, factor_evaluation,
         factor_type_analysis.
"""

from __future__ import annotations

from tools.testers.settings.contracts import ScopePolicy, SettingDefinition, SettingOption
from tools.testers.settings.registry import ApplicationSettings

FACTOR_CANDIDATE_KEYS = ("factor_candidates",)
FACTOR_SET_SELECTION_KEYS = ("factor_set_selections",)
FACTOR_SELECTION_KEYS = ("factor",)
FACTOR_SELECTIONS_KEYS = ("factor_selections",)
FACTOR_SOURCE_KEYS = (
    "factor_owner_ref",
    "factor_git_commit",
    "factor_family_ref",
    "factor_params",
)


def register_factor_source_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    """Register the immutable owner/revision/family candidate builder."""
    app.register_setting(SettingDefinition(
        "factor_owner_ref",
        "因子所有者",
        tab,
        "custom",
        "",
        scope_policy,
        module="factor_execution",
        chip_template="因子所有者: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="选择用户或 Profile 已注册的因子工作区",
        serialization={
            "kind": "factor_owner_selection",
            "display_order": 1,
            "catalog_command": "client catalog owner list",
        },
    ))
    app.register_setting(SettingDefinition(
        "factor_git_commit",
        "Git commit",
        tab,
        "custom",
        "",
        scope_policy,
        module="factor_execution",
        chip_template="Git commit: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="冻结所选所有者因子工作区的精确提交",
        serialization={
            "kind": "factor_revision_selection",
            "display_order": 2,
            "owner_field": "factor_owner_ref",
            "catalog_command": "client catalog revision list",
        },
    ))
    app.register_setting(SettingDefinition(
        "factor_family_ref",
        "因子家族",
        tab,
        "custom",
        "",
        scope_policy,
        module="factor_execution",
        chip_template="因子家族: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="只显示所选 owner 与 Git commit 中可加载的因子家族",
        serialization={
            "kind": "factor_family_selection",
            "display_order": 3,
            "owner_field": "factor_owner_ref",
            "revision_field": "factor_git_commit",
            "catalog_command": "client catalog family list",
        },
    ))
    app.register_setting(SettingDefinition(
        "factor_params",
        "因子参数",
        tab,
        "custom",
        {},
        scope_policy,
        module="factor_execution",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="按因子家族参数定义生成一个冻结的具体因子候选",
        serialization={
            "kind": "factor_parameter_values",
            "display_order": 4,
            "family_field": "factor_family_ref",
            "candidate_field": "factor_candidates",
            "catalog_command": "client catalog factor instantiate",
        },
    ))


def register_factor_execution_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
) -> None:
    warmup_default_if = (
        {
            "engine_mode": {
                "basic": "none",
                "auto": "auto",
                "custom": "auto",
                "exact": "auto",
            },
        }
        if "engine_mode" in app.settings
        else {}
    )
    app.register_setting(SettingDefinition(
        "factor_mode",
        "因子计算模式",
        tab,
        "select",
        "auto",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
        options=(
            SettingOption("auto", "自动选择"),
            SettingOption("precomputed", "预计算后按事件回放"),
            SettingOption("incremental", "随事件增量计算"),
        ),
        chip_template="因子计算: {value}",
    ))
    app.register_setting(SettingDefinition(
        "warmup_mode",
        "前摇窗口",
        tab,
        "select",
        "auto",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
        options=(
            SettingOption("none", "不使用"),
            SettingOption("fixed", "固定时间"),
            SettingOption("auto", "按因子表达式自动推导"),
        ),
        chip_template="前摇窗口: {value}",
        default_if=warmup_default_if,
        help_text="只用于扩大因子计算窗口和 live bar 预热事件；正式信号窗口、绩效统计窗口不随之改变。",
    ))
    app.register_setting(SettingDefinition(
        "warmup_window",
        "前摇时长",
        tab,
        "text",
        "30d",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
        chip_template="前摇时长: {value}",
        visible_if={"warmup_mode": ("fixed",)},
        help_text="固定前摇窗口必须是时间值，例如 30min、5d、60d。",
    ))


def register_factor_candidate_list_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "factor_candidates",
        "因子候选列表",
        tab,
        "custom",
        [],
        scope_policy,
        module="factor_execution",
        chip_template="因子候选: {value}",
        adapter_managed=True,
        show_chip=False,
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
    ))


def register_factor_set_selections_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    """Register reusable Factor Set provenance for concrete selections."""
    app.register_setting(SettingDefinition(
        "factor_set_selections",
        "因子集合来源",
        tab,
        "custom",
        [],
        scope_policy,
        module="factor_execution",
        chip_template="因子集合: {value}",
        adapter_managed=True,
        show_chip=True,
        execution_policy="authoring_only",
        help_text="选择集合后展开为有序具体因子；运行配置同时冻结集合身份与成员因子",
        serialization={
            "kind": "factor_set_selection_list",
            "display_order": 15,
            "multi": True,
            "candidate_field": "factor_candidates",
            "selection_field": "factor_selections",
            "catalog_endpoint": "/api/catalog/factor-sets",
            "detail_endpoint": "/api/catalog/factor-sets/detail",
            "descriptor_endpoint": "/api/catalog/factor-sets/descriptor",
            "native_catalog_action": "catalog",
            "native_detail_action": "members",
            "native_descriptor_action": "descriptor",
            "native_run_input_action": "run-input",
        },
    ))


def register_factor_selection_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "factor",
        "因子",
        tab,
        "select",
        "",
        scope_policy,
        module="factor_execution",
        chip_template="因子: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="从已加载的因子候选中选择本次测试使用的因子；IC 测试可多选，回测使用单个因子。",
        info_overlay={"type": "factor_info"},
        serialization={
            "kind": "factor_selection",
            "display_order": 20,
            "candidate_field": "factor_candidates",
            # 模块内单选为空时回退到页面共享的 factor。
            "shared_page_field": "factor",
            "id_keys": ("alias", "name", "factor_alias"),
            "label_keys": ("alias", "name", "label"),
        },
    ))


def register_factor_selections_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "factor_selections",
        "因子选择",
        tab,
        "custom",
        [],
        scope_policy,
        module="factor_execution",
        chip_template="因子选择: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="从因子候选列表多选；为空时回退到候选列表（先本模块本地候选，再页面全局候选）。",
        info_overlay={"type": "factor_info"},
        serialization={
            "kind": "factor_selection_list",
            "display_order": 30,
            "item_kind": "factor",
            "multi": True,
            "candidate_field": "factor_candidates",
            # 多选为空时回退到候选列表本身：先本地 candidate_field，再其页面全局候选
            "fallback": "candidates",
            "id_keys": ("alias", "name", "factor_alias"),
            "label_keys": ("alias", "name", "label"),
        },
    ))

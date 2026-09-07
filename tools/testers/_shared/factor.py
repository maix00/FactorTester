"""Shared factor execution setting registrations.

Used by: group_test, ic_test, factor_evaluation,
         factor_type_analysis.
"""

from __future__ import annotations

from tools.testers.settings.contracts import (
    ScopePolicy,
    SettingDefinition,
    SettingOption,
    TabMountPoint,
)
from tools.testers.settings.registry import ApplicationSettings
from tools.testers.factor_authoring_contract import factor_identity_serialization

FACTOR_CANDIDATE_KEYS = ("factor_candidates",)
FACTOR_SET_SELECTION_KEYS = ("factor_set_selections",)
FACTOR_SELECTION_KEYS = ("factor",)
FACTOR_SELECTIONS_KEYS = ("factor_selections",)
FACTOR_SOURCE_SELECTION_KEYS = ("factor_source_selections",)
FACTOR_EXECUTION_KEYS = ("factor_mode", "warmup_mode", "warmup_window")


def register_factor_execution_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    warmup_mode_default: str = "auto",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
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
        scope_policy,
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
        warmup_mode_default,
        scope_policy,
        module="factor_execution",
        options=(
            SettingOption("none", "不使用"),
            SettingOption("fixed", "固定时间"),
            SettingOption("auto", "按因子表达式自动推导"),
        ),
        chip_template="前摇窗口: {value}",
        default_if=warmup_default_if,
        help_text=(
            "正式起始日期始终定义输出区间；选择“不使用”时不读取更早数据，"
            "滚动窗口在起始段数据不足时自然产生 NaN。固定或自动预热只扩大"
            "因子计算与 live bar 预热范围，不改变正式信号和绩效统计区间。"
        ),
    ))
    app.register_setting(SettingDefinition(
        "warmup_window",
        "前摇时长",
        tab,
        "text",
        "30d",
        scope_policy,
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
        tab_default_mount_points=(TabMountPoint.LOCAL_SETTINGS,),
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场因子。",
        serialization={
            "kind": "factor_candidate_list",
            "display_order": 10,
            "item_kind": "factor",
            "shared_page_field": "factor_candidates",
            "selection_field": "factor",
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
    ))


def register_factor_source_selections_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    """Register the direct-factor source of the derived candidate pool.

    ``factor_candidates`` is the derived pool consumed by a test.  Direct
    factors must remain distinguishable from members expanded from a factor
    set, otherwise removing one source can silently remove a candidate that
    still belongs to another source.
    """
    app.register_setting(SettingDefinition(
        "factor_source_selections",
        "因子来源",
        tab,
        "custom",
        [],
        scope_policy,
        module="factor_execution",
        chip_template="因子: {value}",
        adapter_managed=True,
        show_chip=False,
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
        show_chip=False,
        execution_policy="authoring_only",
        help_text="选择集合后展开为有序具体因子；运行配置同时冻结集合身份与成员因子",
        serialization={
            "kind": "factor_set_selection_list",
            "display_order": 15,
            "multi": True,
            "candidate_field": "factor_candidates",
            "selection_field": "factor_candidates",
            "catalog_endpoint": "/api/factor-library/factor-sets",
            "detail_endpoint": "/api/factor-library/factor-sets/detail",
            "descriptor_endpoint": "/api/factor-library/factor-sets/descriptor",
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
            **factor_identity_serialization(),
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
            **factor_identity_serialization(),
        },
    ))

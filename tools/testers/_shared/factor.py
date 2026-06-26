"""Shared factor execution setting registrations.

Used by: single_factor_page, group_test, ic_test, factor_evaluation,
         factor_type_analysis.
"""

from __future__ import annotations

from ..contracts import ScopePolicy, SettingDefinition, SettingOption
from ..registry import ApplicationSettings

FACTOR_CANDIDATE_KEYS = ("factor_candidates",)
FACTOR_SELECTION_KEYS = ("factor",)
FACTOR_SELECTIONS_KEYS = ("factor_selections",)


def register_factor_execution_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
) -> None:
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

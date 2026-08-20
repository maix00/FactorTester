"""Shared category-by-group setting registrations (for by_group IC)."""

from __future__ import annotations

from tools.testers.settings.contracts import ScopePolicy, SettingDefinition
from tools.testers.settings.registry import ApplicationSettings

CATEGORY_CANDIDATE_KEYS = ("category_candidates",)
CATEGORY_SELECTION_KEYS = ("category",)


def register_category_candidate_list_base(
    app: ApplicationSettings,
    *,
    tab: str = "category",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "category_candidates",
        "分类候选列表",
        tab,
        "custom",
        [],
        scope_policy,
        module="category_grouping",
        chip_template="分类候选: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="分类候选：数据源内置(数据库) + 用户自定义 + 现场新增；每个分类是一组不相交的路径组。",
        serialization={
            "kind": "category_candidate_list",
            "display_order": 10,
            "item_kind": "category",
            "shared_page_field": "category_candidates",
            "selection_field": "category",
            "category_source": "data_source_categories",
            "candidate_constraint": "category_candidates",
            "fallback_policy": (
                "copy_page_candidates",
                "load_data_source_categories_when_page_empty",
            ),
            "id_keys": ("name", "id"),
            "label_keys": ("name", "label"),
            "mutation_scope": {
                "page": "page_candidates_only",
                "module": "module_candidates_only",
            },
        },
    ))


def register_category_selection_base(
    app: ApplicationSettings,
    *,
    tab: str = "category",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "category",
        "分类",
        tab,
        "select",
        "",
        scope_policy,
        module="category_grouping",
        chip_template="分类: {value}",
        adapter_managed=True,
        show_chip=False,
        help_text="选择数据源提供的分类用于 IC 分组；分类由数据源或用户产品分类提供。",
        info_overlay={"type": "category_detail"},
        serialization={
            "kind": "category_selection",
            "display_order": 20,
            "candidate_field": "category_candidates",
            "candidate_constraint": "category_candidates",
            "shared_page_field": "category",
            "id_keys": ("name", "id"),
            "label_keys": ("name", "label"),
        },
    ))

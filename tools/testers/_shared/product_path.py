"""Shared product path setting registrations."""

from __future__ import annotations

from tools.testers.settings.contracts import ScopePolicy, SettingDefinition
from tools.testers.settings.registry import ApplicationSettings
from tools.products.product_path_selection import ProductPathSelection

PRODUCT_PATH_SELECTION_KEYS = ("product_path_selection",)
PRODUCT_PATH_SELECTIONS_KEYS = ("product_path_selections",)
PRODUCT_PATH_CANDIDATE_KEYS = ("product_path_candidates",)


def register_product_path_selection_base(
    app: ApplicationSettings,
    *,
    tab: str = "product_path_selection",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "product_path_selection",
        "产品路径",
        tab,
        "select",
        None,
        scope_policy,
        module="product_selection",
        chip_template="产品路径: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="选择或内联一组产品路径；若引用用户产品组模板，则保存产品组模板 id。",
        info_overlay={"type": "product_path_selection_products"},
        instance_class=ProductPathSelection,
        serialization={
            "kind": "product_path_selection",
            "display_order": 20,
            # 模块内单选为空时回退到页面共享的 product_path_selection。
            "shared_page_field": "product_path_selection",
            "product_group_reference_keys": (
                "product_group_template_id",
                "path_id",
            ),
            "product_group_source_type": "user_product_group_template",
            "id_keys": (
                "product_path_selection_id",
                "selection_id",
                "id",
            ),
            "manual_path_keys": (
                "paths",
                "selected_paths",
            ),
            "product_group_fields": (
                "product_path_selection_id",
            ),
            "manual_fields": (
                "product_path_selection_id",
                "paths",
            ),
        },
    ))


def register_product_path_selections_base(
    app: ApplicationSettings,
    *,
    tab: str = "product_path_selection",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "product_path_selections",
        "产品路径选择",
        tab,
        "custom",
        [],
        scope_policy,
        module="product_selection",
        chip_template="产品路径选择: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="从产品路径候选列表多选；为空时回退到候选列表（先本模块本地候选，再页面全局候选）。",
        info_overlay={"type": "product_path_selection_products"},
        instance_class=ProductPathSelection,
        serialization={
            "kind": "product_path_selection_list",
            "display_order": 30,
            "item_kind": "product_path_selection",
            "multi": True,
            "candidate_field": "product_path_candidates",
            "candidate_constraint": "product_path_candidates",
            "fallback": "candidates",
            "id_keys": (
                "product_path_selection_id",
                "selection_id",
                "id",
            ),
        },
    ))


def register_product_path_candidate_list_base(
    app: ApplicationSettings,
    *,
    tab: str = "product_path_selection",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "product_path_candidates",
        "产品路径候选列表",
        tab,
        "custom",
        [],
        scope_policy,
        module="product_selection",
        chip_template="产品路径候选: {value}",
        adapter_managed=True,
        show_chip=False,
        execution_policy="authoring_only",
        help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场路径组。",
        serialization={
            "kind": "product_path_candidate_list",
            "display_order": 10,
            "item_kind": "product_path_selection",
            "shared_page_field": "product_path_candidates",
            "selection_field": "product_path_selection",
            "product_group_source": "user_product_group_templates",
            "candidate_constraint": "product_path_candidates",
            "manual_candidate_source": "runtime_manual_path_group",
            "fallback_policy": (
                "copy_page_candidates",
                "load_user_product_groups_when_page_empty",
            ),
            "mutation_scope": {
                "page": "page_candidates_only",
                "module": "module_candidates_only",
            },
            "persist_manual_candidates": False,
            "dedupe_product_groups": True,
            "allow_duplicate_manual_candidates": True,
        },
    ))

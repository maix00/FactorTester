"""ProductSelectionModule — resolves each strategy's product_path_selection.

`ProductSelectionModule.products` deliberately keeps the product-path universe:
for futures that is normally the abstract product/continuous series used for
research and signal coverage checks.  `TermStructureExpandModule` runs later
and records the concrete contracts whose trading life intersects the run
window; it does not require each contract to cover the whole run window.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.products.product_path_selection import ProductPathSelection


class ProductSelectionModule(ExecutableModule):
    key: ClassVar[str] = "product_selection"
    label: ClassVar[str] = "产品选择"

    product_path_selection: ClassVar[FieldRef[Any]] = FieldRef("product_path_selection")
    product_path_candidates: ClassVar[FieldRef[list[Any]]] = FieldRef("product_path_candidates")
    products: ClassVar[FieldRef[frozenset]] = FieldRef("products")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "product_path_candidates": FieldDefinition(
            public=True, label="产品路径候选", default=[], editor="custom", tab="product_path_selection",
            chip_template="产品路径候选: {value}", tab_label="产品路径", tab_order=30,
            tab_default_mount_points=("local-settings",),
            tab_content_adapter="product_path_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场路径组。",
            serialization={
                "kind": "product_path_candidate_list",
                "display_order": 10,
                "item_kind": "product_path_selection",
                "shared_page_field": "product_path_candidates",
                "candidate_constraint": "product_path_candidates",
                "selection_field": "product_path_selection",
                "product_group_source": "user_product_group_templates",
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
        ),
        "product_path_selection": FieldDefinition(
            public=True, label="产品路径", default=None, editor="select", tab="product_path_selection",
            chip_template="产品路径: {value}", tab_label="产品路径", tab_order=30,
            tab_content_adapter="product_path_selection",
            adapter_managed=True, show_chip=False,
            execution_policy="authoring_only",
            help_text="选择或内联一组产品路径；若引用用户产品组模板，则保存产品组模板 id。",
            info_overlay={"type": "product_path_selection_products"},
            instance_class=ProductPathSelection,
            serialization={
                "kind": "product_path_selection",
                "display_order": 20,
                "shared_page_field": "product_path_selection",
                "candidate_constraint": "product_path_candidates",
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
                "product_group_fields": ("product_path_selection_id",),
                "manual_fields": (
                    "product_path_selection_id",
                    "paths",
                ),
            },
        ),
    }

    resolve_product_selection: ClassVar[Flow] = Flow(
        "resolve_product_selection", inputs=(product_path_selection,), outputs=(products,),
        phase=Phase.PRE_REPLAY, order=15,
        description="解析产品路径",
        compute=lambda state, ctx: _resolve_product_selection(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (resolve_product_selection,)


def _resolve_product_selection(state, ctx) -> None:
    by_selection_id: dict[str, list] = defaultdict(list)
    for strategy in state.strategy_configs:
        selection = state.config_for(strategy).get(ProductSelectionModule.product_path_selection)
        by_selection_id[selection.selection_id].append(strategy)

    for selection_id, strategies in by_selection_id.items():
        selection = state.config_for(strategies[0]).get(ProductSelectionModule.product_path_selection)
        resolved = frozenset(selection.products)  # parsed once per unique selection_id
        for strategy in strategies:
            ctx.set_for(ProductSelectionModule.products, strategy, resolved)

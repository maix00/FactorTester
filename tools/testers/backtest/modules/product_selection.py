"""ProductSelectionModule — resolves each strategy's product_path_selection
into a concrete `products` set; TermStructureExpandModule later overwrites
that same field once abstract products are expanded into per-timestamp
concrete contracts (issue-114 step 3.3/8)."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.products.product_path_selection import ProductPathSelection

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.products.product_path_selection import ProductPathSelection


class ProductSelectionModule(ExecutableModule):
    key: ClassVar[str] = "product_selection"
    label: ClassVar[str] = "产品选择"

    product_path_selection: ClassVar[FieldRef[Any]] = FieldRef("product_path_selection")
    product_path_candidates: ClassVar[FieldRef[list[Any]]] = FieldRef("product_path_candidates")
    products: ClassVar[FieldRef[frozenset]] = FieldRef("products")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "product_path_candidates": FieldDefinition(
            public=True, default=[], control_template="custom", tab="product_path_selection",
            chip_template="产品路径候选: {value}", tab_label="产品路径", tab_order=30,
            help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场路径组。",
            serialization={
                "kind": "product_path_candidate_list",
                "display_order": 10,
                "item_kind": "product_path_selection",
                "shared_page_field": "product_path_candidates",
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
            public=True, default=None, control_template="select", tab="product_path_selection",
            chip_template="产品路径: {value}", tab_label="产品路径", tab_order=30,
            help_text="选择或内联一组产品路径；若引用用户产品组模板，则保存产品组模板 id。",
            info_overlay={"type": "product_path_selection_products"},
            instance_class=ProductPathSelection,
            serialization={
                "kind": "product_path_selection",
                "display_order": 20,
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
        phase=Phase.PRE_REPLAY, order=15, compute=lambda account, ctx: _resolve_product_selection(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (resolve_product_selection,)


def _resolve_product_selection(account, ctx) -> None:
    by_selection_id: dict[str, list] = defaultdict(list)
    for strategy in account.strategy_configs:
        selection = account.config_for(strategy).get(ProductSelectionModule.product_path_selection)
        by_selection_id[selection.selection_id].append(strategy)

    for selection_id, strategies in by_selection_id.items():
        selection = account.config_for(strategies[0]).get(ProductSelectionModule.product_path_selection)
        resolved = frozenset(selection.products)  # parsed once per unique selection_id
        for strategy in strategies:
            ctx.set_for(ProductSelectionModule.products, strategy, resolved)


class TermStructureExpandModule(ExecutableModule):
    """Expands abstract products (e.g. a continuous-contract alias) into
    the concrete per-timestamp contract that's actually tradeable.
    Overwrites ProductSelectionModule.products in place — same FieldRef,
    not a separate field — so any downstream reader of `.products` always
    sees expanded contracts."""

    key: ClassVar[str] = "term_structure_expand"
    label: ClassVar[str] = "合约展开"

    expand_term_structure: ClassVar[Flow] = Flow(
        "expand_term_structure",
        inputs=(ProductSelectionModule.products,),
        outputs=(ProductSelectionModule.products,),
        phase=Phase.PRE_REPLAY, order=30,
        after=(ProductSelectionModule.resolve_product_selection,),
        compute=lambda account, ctx: _expand_term_structure(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (expand_term_structure,)


def _expand_term_structure(account, ctx) -> None:
    """Most products aren't term-structure products (no continuous-contract
    chain to expand) — for those, expansion is the identity. Products that
    do support term structure (`product.supports_term_structure()`)
    delegate to their own resolution helper; the specific per-timestamp
    contract-selection rule is product-family-specific and out of scope to
    reimplement here, so this only does the no-op passthrough this round."""
    for strategy in account.strategy_configs:
        products = ctx.get_for(ProductSelectionModule.products, strategy)
        ctx.set_for(ProductSelectionModule.products, strategy, products)

"""ProductSelectionModule — resolves each strategy's product_path_selection
into a concrete `products` set; TermStructureExpandModule later overwrites
that same field once abstract products are expanded into per-timestamp
concrete contracts (issue-114 step 3.3/8)."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase

if TYPE_CHECKING:
    from tools.products.Product import Product
    from tools.products.product_path_selection import ProductPathSelection


class ProductSelectionModule(ExecutableModule):
    key: ClassVar[str] = "product_selection"
    label: ClassVar[str] = "产品选择"

    product_path_selection: ClassVar[FieldRef[Any]] = FieldRef("product_path_selection")
    products: ClassVar[FieldRef[frozenset]] = FieldRef("products")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "product_path_selection": FieldDefinition(public=True, control_template="custom", tab="product_path_selection"),
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

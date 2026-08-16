"""Backend-owned authoring contracts for IC core axes."""

from tools.testers.analysis_graph import (
    CoreAxisDefinition,
)
from tools.testers.field_spec import ValueDescriptor


def ic_core_axis_definitions() -> tuple[CoreAxisDefinition, ...]:
    return (
        CoreAxisDefinition(
            key="product_scope_ref", label="产品范围", authoring_key="product_scope_refs",
            value_descriptor=ValueDescriptor(
                "reference", cardinality="many", editor="catalog",
                item_type="reference", ref_kind="stable_product_scope_ref",
                option_source="catalog.product_scope", resolver="selected_product_paths",
            ),
            source_adapter="selected_product_paths", accepts_many=True,
            resolution_adapter="stable_product_scope",
            help_text="选择一个或多个冻结产品路径；每个产品范围独立形成 Job",
            value_contract={
                "item_type": "stable_product_scope_ref",
                "minimum_items": 1,
                "unique_items": True,
            },
        ),
        CoreAxisDefinition(
            key="factor_ref", label="因子", authoring_key="factor_refs",
            value_descriptor=ValueDescriptor(
                "reference", cardinality="many", editor="catalog",
                item_type="reference", ref_kind="frozen_factor_ref",
                option_source="catalog.factor", resolver="selected_factors",
            ),
            source_adapter="selected_factors", accepts_many=True,
            resolution_adapter="frozen_factor_members",
            help_text="选择冻结因子或因子集合；集合在冻结运行配置时展开为具体因子",
            value_contract={
                "item_type": "frozen_factor_ref",
                "minimum_items": 1,
                "unique_items": True,
            },
        ),
        CoreAxisDefinition(
            key="horizon", label="前瞻收益期", authoring_key="horizon",
            value_descriptor=ValueDescriptor(
                "grid", cardinality="many", editor="base_multiplier_grid",
                item_type="integer",
            ),
            accepts_many=True,
            resolution_adapter="per_factor_frequency",
            help_text="作者输入基准×倍数；运行配置按各因子频率冻结物理收益期",
            value_contract={
                "modes": ["scale_aware", "explicit"],
                "default_mode": "scale_aware",
                "base_values": ["signal"],
                "allow_physical_frequency_base": True,
                "multiplier_minimum": 1,
                "multiplier_integer_only": True,
                "minimum_multipliers": 1,
            },
        ),
        CoreAxisDefinition(
            key="entry_delay_bars", label="入场延迟", authoring_key="entry_delay_bars",
            value_descriptor=ValueDescriptor(
                "array", cardinality="many", editor="non_negative_integer_list",
                item_type="integer", minimum=0,
            ),
            accepts_many=True,
            help_text="单位为各因子自己的信号 bar",
            value_contract={
                "item_type": "integer",
                "minimum": 0,
                "minimum_items": 1,
                "unique_items": True,
            },
        ),
        CoreAxisDefinition(
            key="method", label="IC 方法", authoring_key="methods",
            value_descriptor=ValueDescriptor(
                "enum", cardinality="many", editor="segmented_multi_select",
                item_type="string",
                options=(
                    ("rank", "Rank IC"),
                    ("pearson", "Pearson IC"),
                ),
            ),
            accepts_many=True,
            value_contract={"minimum_items": 1, "unique_items": True},
        ),
        CoreAxisDefinition(
            key="return_price_basis", label="收益口径", authoring_key="return_price_basis",
            value_descriptor=ValueDescriptor(
                "enum", editor="select", options=(
                    ("next_open_to_open_adjusted", "下一期开盘到开盘（复权）"),
                    ("next_close_to_close_adjusted", "下一期收盘到收盘（复权）"),
                ),
            ),
            value_contract={"required": True},
        ),
    )


__all__ = ["ic_core_axis_definitions"]

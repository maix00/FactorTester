"""Backend-owned authoring contracts for IC core axes."""

from tools.testers.analysis_graph import (
    AnalysisOptionDefinition,
    CoreAxisDefinition,
)


def ic_core_axis_definitions() -> tuple[CoreAxisDefinition, ...]:
    return (
        CoreAxisDefinition(
            "product_scope_ref", "产品范围", "product_scope_refs",
            "reference_multi_select", "selected_product_paths", True,
            "stable_product_scope",
            help_text="选择一个或多个冻结产品路径；每个产品范围独立形成 Job",
            value_contract={
                "item_type": "stable_product_scope_ref",
                "minimum_items": 1,
                "unique_items": True,
            },
        ),
        CoreAxisDefinition(
            "factor_ref", "因子", "factor_refs",
            "reference_multi_select", "selected_factors", True,
            "frozen_factor_members",
            help_text="选择冻结因子或因子集合；集合在冻结运行配置时展开为具体因子",
            value_contract={
                "item_type": "frozen_factor_ref",
                "minimum_items": 1,
                "unique_items": True,
            },
        ),
        CoreAxisDefinition(
            "horizon", "前瞻收益期", "horizon",
            "base_multiplier_grid", accepts_many=True,
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
            "entry_delay_bars", "入场延迟", "entry_delay_bars",
            "non_negative_integer_list", accepts_many=True,
            help_text="单位为各因子自己的信号 bar",
            value_contract={
                "item_type": "integer",
                "minimum": 0,
                "minimum_items": 1,
                "unique_items": True,
            },
        ),
        CoreAxisDefinition(
            "method", "IC 方法", "methods", "segmented_multi_select",
            accepts_many=True,
            options=(
                AnalysisOptionDefinition("rank", "Rank IC"),
                AnalysisOptionDefinition("pearson", "Pearson IC"),
            ),
            value_contract={"minimum_items": 1, "unique_items": True},
        ),
        CoreAxisDefinition(
            "return_price_basis", "收益口径", "return_price_basis", "select",
            options=(
                AnalysisOptionDefinition(
                    "next_open_to_open_adjusted", "下一期开盘到开盘（复权）",
                ),
                AnalysisOptionDefinition(
                    "next_close_to_close_adjusted", "下一期收盘到收盘（复权）",
                ),
            ),
            value_contract={"required": True},
        ),
    )


__all__ = ["ic_core_axis_definitions"]

"""Backend-owned authoring contracts for IC core axes."""

from tools.testers.analysis_graph import (
    AnalysisOptionDefinition,
    CoreAxisDefinition,
)


def ic_core_axis_definitions() -> tuple[CoreAxisDefinition, ...]:
    return (
        CoreAxisDefinition(
            "product_scope_ref", "产品范围", "product_path_selections",
            "reference_multi_select", "selected_product_paths", True,
            "stable_product_scope",
            help_text="选择一个或多个冻结产品路径；每个产品范围独立形成 Job",
        ),
        CoreAxisDefinition(
            "factor_ref", "因子", "factor_selections",
            "reference_multi_select", "selected_factors", True,
            "frozen_factor_members",
            help_text="选择冻结因子或因子集合；集合在冻结运行配置时展开为具体因子",
        ),
        CoreAxisDefinition(
            "horizon", "前瞻收益期", "forward_return_horizons",
            "base_multiplier_grid", accepts_many=True,
            resolution_adapter="per_factor_frequency",
            help_text="作者输入基准×倍数；运行配置按各因子频率冻结物理收益期",
        ),
        CoreAxisDefinition(
            "entry_delay_bars", "入场延迟", "ic_lags",
            "non_negative_integer_list", accepts_many=True,
            help_text="单位为各因子自己的信号 bar",
        ),
        CoreAxisDefinition(
            "method", "IC 方法", "ic_correlation", "segmented_multi_select",
            accepts_many=True,
            options=(
                AnalysisOptionDefinition("rank", "Rank IC"),
                AnalysisOptionDefinition("pearson", "Pearson IC"),
                AnalysisOptionDefinition("both", "Rank + Pearson"),
            ),
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
        ),
    )


__all__ = ["ic_core_axis_definitions"]

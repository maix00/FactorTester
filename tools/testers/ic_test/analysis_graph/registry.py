"""Registered IC analyses and their typed inputs/outputs."""

from __future__ import annotations

from functools import lru_cache

from tools.testers.analysis_graph import (
    AnalysisGraphDefinition,
    AnalysisInputContract,
    AnalysisMapping,
    AnalysisParameterDefinition,
    AnalysisTargetCardinality,
    AnalysisTargetOrigin,
    AnalysisTypeDefinition,
    CoreTestDefinition,
)
from tools.testers.ic_test.core import IC_CORE_AXES, IC_CORE_OUTPUT_KINDS


def _single_core_input(kind: str) -> AnalysisInputContract:
    return AnalysisInputContract(
        accepted_kinds=(kind,),
        target_origins=(AnalysisTargetOrigin.CORE,),
    )


@lru_cache(maxsize=1)
def ic_analysis_graph_definition() -> AnalysisGraphDefinition:
    """Return the sole backend-owned IC analysis registry.

    The current executable analyses all consume core IC outputs.  The generic
    graph contract supports analysis-on-analysis dependencies, but none are
    advertised until an executor actually implements that input type.
    """

    analyses = (
        AnalysisTypeDefinition(
            key="ic_resample_stability",
            label="IC 重采样稳定性",
            order=10,
            help_text="按固定观测间隔重采样同一条 IC 序列并比较均值、波动、IR 与 t 统计",
            input_contract=_single_core_input("ic_series"),
            output_kind="ic_resample_statistics",
            parameters=(AnalysisParameterDefinition(
                key="sampling_intervals",
                label="重采样间隔",
                control_template="positive_integer_list",
                default=[5],
                help_text="单位为有效 IC 观测数，不是入场延迟或自相关阶数",
            ),),
            result_capabilities=("ic_statistics",),
        ),
        AnalysisTypeDefinition(
            key="rolling_ic_stability",
            label="滚动 IC 稳定性",
            order=20,
            help_text="在同一条 IC 序列上按信号数计算滚动统计",
            input_contract=_single_core_input("ic_series"),
            output_kind="rolling_ic_statistics",
            parameters=(AnalysisParameterDefinition(
                key="rolling_windows",
                label="滚动窗口",
                control_template="signal_count_list",
                default=[20],
                help_text="窗口单位固定为有效信号数",
            ),),
            result_capabilities=("ic_rolling_stability",),
        ),
        AnalysisTypeDefinition(
            key="period_diagnostics",
            label="分期诊断",
            order=30,
            help_text="按日历分期检查 IC 的可估计性、方向与稳定性",
            input_contract=_single_core_input("ic_series"),
            output_kind="ic_period_diagnostics",
            result_capabilities=("ic_period_diagnostics",),
        ),
        AnalysisTypeDefinition(
            key="ic_autocorrelation",
            label="IC 自相关",
            order=40,
            help_text="计算同一条 IC 序列的自相关路径",
            input_contract=_single_core_input("ic_series"),
            output_kind="ic_autocorrelation",
            parameters=(AnalysisParameterDefinition(
                key="maximum_lag",
                label="最大阶数",
                control_template="number",
                default=20,
                minimum=1,
                step=1,
            ),),
            result_capabilities=("ic_statistics",),
        ),
        AnalysisTypeDefinition(
            key="quantile_portfolio_statistics",
            label="分组组合统计",
            order=50,
            help_text="使用核心测试保留的因子值、前瞻收益和可投资性面板做向量化筛选",
            input_contract=_single_core_input("ic_series"),
            output_kind="quantile_portfolio_statistics",
            parameters=(AnalysisParameterDefinition(
                key="portfolio",
                label="分组组合参数",
                control_template="quantile_portfolio_statistics",
                default={
                    "group_count": 5,
                    "modes": ["no_fee", "fee_margin_target"],
                    "target_margin_utilization": 0.30,
                    "initial_capital": 1.0,
                    "include_return_series": False,
                },
            ),),
            required_core_inputs=(
                "factor_values", "forward_returns", "eligibility",
            ),
            result_capabilities=("ic_quantile_portfolio_statistics",),
        ),
        AnalysisTypeDefinition(
            key="forward_horizon_half_life",
            label="前瞻收益半衰期",
            order=60,
            help_text="合并同一因子、产品范围、延迟和 IC 方法下的多个前瞻收益期",
            input_contract=AnalysisInputContract(
                accepted_kinds=("ic_statistics",),
                target_origins=(AnalysisTargetOrigin.CORE,),
                cardinality=AnalysisTargetCardinality.MANY,
                mapping=AnalysisMapping.COMBINE,
                minimum_targets=2,
                maximum_targets=None,
                same_axes=(
                    "product_scope_ref",
                    "factor_ref",
                    "entry_delay_bars",
                    "method",
                ),
                varying_axes=("horizon",),
            ),
            output_kind="forward_horizon_half_life",
            result_capabilities=("ic_holding_half_life",),
        ),
    )
    return AnalysisGraphDefinition(
        key="ic_analysis_graph",
        label="IC 核心测试与附加分析",
        core_test=CoreTestDefinition(
            label="核心 IC 测试",
            axes=IC_CORE_AXES,
            output_kinds=IC_CORE_OUTPUT_KINDS,
        ),
        analysis_types=analyses,
    )


__all__ = ["ic_analysis_graph_definition"]

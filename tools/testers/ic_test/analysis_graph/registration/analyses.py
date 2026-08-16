"""Built-in IC auxiliary-analysis definitions."""

from tools.testers.analysis_graph import (
    AnalysisChipDefinition,
    AnalysisInputContract,
    AnalysisMapping,
    AnalysisParameterDefinition,
    AnalysisTargetCardinality,
    AnalysisTargetOrigin,
    AnalysisTypeDefinition,
)
from tools.testers.field_spec import ValueDescriptor, infer_value_descriptor


def _single_core_input(kind: str) -> AnalysisInputContract:
    return AnalysisInputContract(
        accepted_kinds=(kind,),
        target_origins=(AnalysisTargetOrigin.CORE,),
    )


def builtin_ic_analyses() -> tuple[AnalysisTypeDefinition, ...]:
    return (
        _single_series_analysis(
            "ic_resample_stability", "IC 重采样稳定性", 10,
            "ic_resample_statistics", "sampling_intervals", "重采样间隔",
            "positive_integer_list", [5], "ic_statistics",
            "按固定观测间隔重采样同一条 IC 序列并比较均值、波动、IR 与 t 统计",
            "单位为有效 IC 观测数，不是入场延迟或自相关阶数",
            chip_label="重采样",
            chip_template="重采样: {sampling_intervals}",
        ),
        _single_series_analysis(
            "rolling_ic_stability", "滚动 IC 稳定性", 20,
            "rolling_ic_statistics", "rolling_windows", "滚动窗口",
            "signal_count_list", [20], "ic_rolling_stability",
            "在同一条 IC 序列上按信号数计算滚动统计",
            "窗口单位固定为有效信号数",
            chip_label="滚动窗口",
            chip_template="滚动: {rolling_windows}",
        ),
        _single_series_analysis(
            "period_diagnostics", "分期诊断", 30,
            "ic_period_diagnostics", "periods", "分期规则",
            "ic_period_grid", [], "ic_period_diagnostics",
            "按日历分期检查 IC 的可估计性、方向与稳定性",
            chip_label="分期诊断",
            chip_template="分期: {periods}",
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
                value_descriptor=ValueDescriptor(
                    "integer", editor="input", minimum=1, step=1,
                ),
                default=20,
            ),),
            result_capabilities=("ic_statistics",),
            chip=AnalysisChipDefinition(
                key="ic_autocorrelation",
                label="自相关",
                template="自相关: {maximum_lag}",
                parameter_keys=("maximum_lag",),
                order=40,
            ),
        ),
        _quantile_portfolio_analysis(),
        _forward_horizon_half_life(),
    )


def _single_series_analysis(
    key: str,
    label: str,
    order: int,
    output_kind: str,
    parameter_key: str,
    parameter_label: str,
    editor: str,
    default,
    result_capability: str,
    help_text: str,
    parameter_help: str = "",
    *,
    chip_label: str,
    chip_template: str,
) -> AnalysisTypeDefinition:
    return AnalysisTypeDefinition(
        key=key,
        label=label,
        order=order,
        help_text=help_text,
        input_contract=_single_core_input("ic_series"),
        output_kind=output_kind,
        parameters=(AnalysisParameterDefinition(
            key=parameter_key,
            label=parameter_label,
            value_descriptor=_analysis_value_descriptor(editor, default, parameter_key),
            default=default,
            help_text=parameter_help,
        ),),
        result_capabilities=(result_capability,),
        chip=AnalysisChipDefinition(
            key=key,
            label=chip_label,
            template=chip_template,
            parameter_keys=(parameter_key,),
            order=order,
        ),
    )


def _analysis_value_descriptor(
    editor: str,
    default,
    key: str,
) -> ValueDescriptor:
    """Return the typed contract for one registered analysis parameter."""
    if editor == "positive_integer_list":
        return ValueDescriptor(
            "array", cardinality="many", editor=editor,
            item_type="integer", minimum=1,
        )
    if editor == "signal_count_list":
        return ValueDescriptor(
            "array", cardinality="many", editor=editor,
            item_type="object", schema={"item_fields": ["unit", "value"]},
        )
    if editor == "ic_period_grid":
        return ValueDescriptor(
            "grid", cardinality="many", editor=editor,
            item_type="period", schema={"calendar": True},
        )
    return infer_value_descriptor(editor, default, field_key=key)


def _quantile_portfolio_analysis() -> AnalysisTypeDefinition:
    return AnalysisTypeDefinition(
        key="quantile_portfolio_statistics",
        label="分组组合统计",
        order=50,
        help_text="使用核心测试保留的因子值、前瞻收益和可投资性面板做向量化筛选",
        input_contract=AnalysisInputContract(
            accepted_kinds=("factor_values", "forward_returns", "eligibility"),
            target_origins=(AnalysisTargetOrigin.CORE,),
        ),
        output_kind="quantile_portfolio_statistics",
        parameters=(AnalysisParameterDefinition(
            key="portfolio",
            label="分组组合参数",
            value_descriptor=ValueDescriptor(
                "object", editor="quantile_portfolio_statistics",
                schema={
                    "required": ["group_count", "modes"],
                    "properties": {
                        "group_count": {"value_type": "integer", "minimum": 2},
                        "modes": {"value_type": "enum", "cardinality": "many"},
                        "target_margin_utilization": {"value_type": "number"},
                        "initial_capital": {"value_type": "number"},
                        "include_return_series": {"value_type": "boolean"},
                    },
                },
            ),
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
        chip=AnalysisChipDefinition(
            key="quantile_portfolio_statistics",
            label="分组组合",
            template="分组组合: {portfolio}",
            parameter_keys=("portfolio",),
            order=50,
        ),
    )


def _forward_horizon_half_life() -> AnalysisTypeDefinition:
    return AnalysisTypeDefinition(
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
                "return_price_basis",
            ),
            varying_axes=("horizon",),
        ),
        output_kind="forward_horizon_half_life",
        result_capabilities=("ic_holding_half_life",),
        chip=AnalysisChipDefinition(
            key="forward_horizon_half_life",
            label="半衰期",
            template="前瞻收益半衰期",
            order=60,
        ),
    )


__all__ = ["builtin_ic_analyses"]

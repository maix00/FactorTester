"""Flat authoring fields compiled into typed IC analysis nodes."""

from __future__ import annotations

from tools.testers.settings.contracts import ScopePolicy, SettingDefinition
from tools.testers.settings.registry import ApplicationSettings


def register_analysis_fields(app: ApplicationSettings) -> None:
    app.register_setting(SettingDefinition(
        "ic_decay_lags", "IC 重采样间隔", "delay", "ic_decay_grid", [5],
        ScopePolicy.LOCAL_ONLY, module="ic_delay",
        help_text=(
            "按每 N 个 IC 观测抽取一个样本，分别报告重采样后的均值、波动、IR 与 t 统计；"
            "不是入场延迟或自相关阶数"
        ),
        chip_template="重采样间隔: {value}",
    ))
    app.register_setting(SettingDefinition(
        "rolling_window", "滚动窗口", "summary", "number", 20,
        ScopePolicy.LOCAL_ONLY, module="ic_summary", minimum=2, step=1,
        chip_template="滚动窗口: {value}",
    ))
    app.register_setting(SettingDefinition(
        "quantile_portfolio_statistics", "分组组合统计",
        "quantile_portfolio_statistics", "custom",
        {
            "enabled": True,
            "group_count": 5,
            "modes": ["no_fee", "fee_margin_target"],
            "target_margin_utilization": 0.30,
            "initial_capital": 1.0,
            "include_return_series": False,
        },
        ScopePolicy.LOCAL_ONLY,
        module="quantile_portfolio_statistics",
        help_text=(
            "把 IC 结果转换为向量化分组组合统计；包含无费率和按品种比例费率/"
            "固定保证金利用率模式。 Avg Turnover 是目标名义权重变化代理，"
            "不含真实成交、整手和流动性。"
        ),
        chip_template="分组组合: {value}",
        serialization={
            "kind": "quantile_portfolio_statistics",
            "display_order": 10,
            "modes": ["no_fee", "fee_margin_target"],
            "turnover_semantics": "target_weight_proxy",
        },
    ))

"""Fields that author the IC core-test matrix."""

from __future__ import annotations

from tools.testers.settings.contracts import (
    ScopePolicy,
    SettingDefinition,
    SettingOption,
)
from tools.testers.settings.registry import ApplicationSettings


def register_core_fields(app: ApplicationSettings) -> None:
    app.register_setting(SettingDefinition(
        "forward_return_horizons", "前瞻收益期", "return_frequency",
        "ic_horizon_grid", {"sampling": "scale_aware"}, ScopePolicy.LOCAL_ONLY,
        module="return_frequency",
        help_text=(
            "可按因子频率自动生成，或冻结多个基准与倍数；"
            "首个结果作为默认展示收益期"
        ),
        chip_template="收益期: {value}",
    ))
    app.register_setting(SettingDefinition(
        "return_price_basis", "收益口径", "return_frequency", "select",
        "next_open_to_open_adjusted", ScopePolicy.LOCAL_ONLY,
        module="return_definition",
        options=(
            SettingOption("next_open_to_open_adjusted", "下一期开盘到开盘（复权）"),
            SettingOption("next_close_to_close_adjusted", "下一期收盘到收盘（复权）"),
        ),
        chip_template="收益口径: {value}",
    ))
    app.register_setting(SettingDefinition(
        "ic_lags", "入场延迟", "delay", "ic_delay_grid", [0],
        ScopePolicy.LOCAL_ONLY, module="ic_delay",
        help_text=(
            "以信号 bar 为单位分别计算多个延迟；"
            "0 表示信号可成交时立即进入，首项用于默认展示"
        ),
        chip_template="延迟: {value}",
    ))
    app.register_setting(SettingDefinition(
        "ic_correlation", "默认 IC", "ic_method", "select", "rank",
        ScopePolicy.LOCAL_ONLY, module="ic_method",
        options=(
            SettingOption("rank", "Cross-sectional Rank IC"),
            SettingOption("pearson", "Cross-sectional Pearson IC"),
            SettingOption("both", "Rank IC + Pearson IC"),
        ),
        chip_template="IC: {value}",
    ))

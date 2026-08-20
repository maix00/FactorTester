"""Shared market data setting registrations."""

from __future__ import annotations

from tools.testers.settings.contracts import ScopePolicy, SettingDefinition, SettingOption
from tools.testers.settings.registry import ApplicationSettings

MARKET_DATA_SELECTION_KEYS = ("data_source", "frequency")


def register_market_data_base(
    app: ApplicationSettings,
    *,
    include_price_type: bool,
) -> None:
    app.register_setting(SettingDefinition(
        "data_source",
        "数据源",
        "data_source",
        "custom",
        [],
        ScopePolicy.LOCAL_ONLY,
        module="market_data_source",
        options=(),
        chip_template="数据源: {value}",
        serialization={
            "kind": "data_source_selection", "multi": True, "display_order": 10,
        },
    ))
    app.register_setting(SettingDefinition(
        "frequency",
        "频率",
        "frequency",
        "select",
        "",
        ScopePolicy.LOCAL_ONLY,
        module="market_data_frequency",
        options=(SettingOption("", "自动"),),
        chip_template="频率: {value}",
        serialization={"display_order": 20},
    ))
    if include_price_type:
        app.register_setting(SettingDefinition(
            "price_type",
            "价格类型",
            "price_type",
            "select",
            "adjusted",
            ScopePolicy.LOCAL_ONLY,
            module="price_transform",
            options=(
                SettingOption("adjusted", "复权"),
                SettingOption("raw", "原始"),
                SettingOption("sma", "SMA 平滑"),
                SettingOption("ema", "EMA 平滑"),
            ),
            chip_template="价格: {value}",
            help_text="行业常见价格处理包括复权、原始价格、简单移动平均和指数移动平均。",
            serialization={"display_order": 30},
        ))

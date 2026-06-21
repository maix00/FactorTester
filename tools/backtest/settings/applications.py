"""Built-in backtest application setting registrations."""

from __future__ import annotations

from .contracts import (
    ScopePolicy,
    SettingDefinition,
    SettingOption,
    SettingTab,
    TabMountPoint,
)
from .registry import ApplicationSettings, BacktestSettingRegistry


def group_test_settings() -> ApplicationSettings:
    app = ApplicationSettings("group_test")
    for tab in (
        SettingTab("engine", "执行引擎", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 10),
        SettingTab("capital", "资金", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 20),
        SettingTab("rebalance", "调仓", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 30),
        SettingTab("cost", "费用", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 40),
        SettingTab("liquidity", "流动性", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 50),
    ):
        app.register_tab(tab)
    app.register_setting(SettingDefinition(
        "engine",
        "回测引擎",
        "engine",
        "select",
        "native",
        ScopePolicy.LOCAL_ONLY,
        options=(
            SettingOption("native", "GTHT 事件驱动回测工具"),
            SettingOption("backtrader", "Backtrader 事件驱动回测工具"),
            SettingOption("qlib", "Qlib 事件驱动回测工具"),
            SettingOption("zipline", "Zipline 事件驱动回测工具"),
        ),
        chip_template="引擎: {value}",
    ))
    app.register_setting(SettingDefinition(
        "factor_mode",
        "因子计算模式",
        "engine",
        "select",
        "auto",
        ScopePolicy.LOCAL_ONLY,
        options=(
            SettingOption("auto", "自动选择"),
            SettingOption("precomputed", "预计算后按事件回放"),
            SettingOption("incremental", "随事件增量计算"),
        ),
        chip_template="因子计算: {value}",
    ))
    app.register_setting(SettingDefinition(
        "initial_capital",
        "初始资金",
        "capital",
        "number",
        100_000_000.0,
        ScopePolicy.GROUP_OVERRIDE,
        minimum=0.01,
        step=10_000.0,
        chip_template="资金: {value}",
    ))
    app.register_setting(SettingDefinition(
        "rebalance_mode",
        "调仓规则",
        "rebalance",
        "select",
        "each_period",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("each_period", "每期调仓"),
            SettingOption("buy_and_hold", "买入持有"),
            SettingOption("recycle", "退出后再配置"),
        ),
        chip_template="调仓: {value}",
    ))
    app.register_setting(SettingDefinition(
        "fee_mode",
        "费用规则",
        "cost",
        "select",
        "market",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("none", "无费用"),
            SettingOption("market", "市场历史费率"),
            SettingOption("custom", "自定义费率"),
        ),
        chip_template="费用: {value}",
    ))
    app.register_setting(SettingDefinition(
        "liquidity_mode",
        "流动性规则",
        "liquidity",
        "select",
        "infinite",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("infinite", "无限流动性"),
            SettingOption("volume_participation", "成交量参与率"),
        ),
        chip_template="流动性: {value}",
    ))
    app.register_setting(SettingDefinition(
        "participation_rate",
        "成交量参与率",
        "liquidity",
        "number",
        0.1,
        ScopePolicy.GROUP_OVERRIDE,
        minimum=0.0,
        maximum=1.0,
        step=0.01,
        chip_template="参与率: {value}",
    ))
    return app


backtest_setting_registry = BacktestSettingRegistry()
backtest_setting_registry.register(group_test_settings())

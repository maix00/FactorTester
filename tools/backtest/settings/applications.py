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
        SettingTab(
            "engine", "执行引擎", (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid", 10, (TabMountPoint.LOCAL_SETTINGS,),
        ),
        SettingTab("capital", "资金", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 20),
        SettingTab("allocation", "分配", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 25),
        SettingTab("rebalance", "调仓", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 30),
        SettingTab("cost", "费用", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 40),
        SettingTab("liquidity", "流动性", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 50),
        SettingTab("market_rules", "市场规则", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 60),
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
        "allocation_policy",
        "组合分配",
        "allocation",
        "select",
        "inverse_volatility",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("inverse_volatility", "等风险（波动率倒数）"),
            SettingOption("equal_notional", "等市值"),
            SettingOption("equal_margin", "等保证金（对照）"),
        ),
        chip_template="分配: {value}",
    ))
    app.register_setting(SettingDefinition(
        "volatility_lookback",
        "波动率回看期数",
        "allocation",
        "number",
        20,
        ScopePolicy.GROUP_OVERRIDE,
        minimum=2,
        step=1,
        chip_template="波动率窗口: {value}",
    ))
    app.register_setting(SettingDefinition(
        "rebalance_mode",
        "调仓规则",
        "rebalance",
        "select",
        "on_factor_signal",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("on_factor_signal", "按因子频率调仓"),
            SettingOption("buy_and_hold", "买入持有"),
            SettingOption("membership_change", "成员变化时调仓"),
            SettingOption("scheduled", "按日历计划调仓"),
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
    app.register_setting(SettingDefinition(
        "market_rule_fallback",
        "历史规则缺失处理",
        "market_rules",
        "select",
        "latest_available",
        ScopePolicy.LOCAL_ONLY,
        options=(
            SettingOption("latest_available", "使用最新规则并标记近似"),
            SettingOption("strict_historical", "缺失即报错"),
            SettingOption("configured_default", "使用注册默认值并标记近似"),
        ),
        chip_template="规则回退: {value}",
    ))
    return app


backtest_setting_registry = BacktestSettingRegistry()
backtest_setting_registry.register(group_test_settings())

"""Built-in backtest application setting registrations."""

from __future__ import annotations

from .contracts import (
    ScopePolicy,
    SettingDefinition,
    SettingOption,
    SettingScope,
    SettingTab,
)
from .registry import ApplicationSettings, BacktestSettingRegistry


def group_test_settings() -> ApplicationSettings:
    app = ApplicationSettings("group_test")
    for tab in (
        SettingTab("engine", "执行引擎", "settings-grid", 10),
        SettingTab("capital", "资金", "settings-grid", 20),
        SettingTab("rebalance", "调仓", "settings-grid", 30),
        SettingTab("cost", "费用", "settings-grid", 40),
        SettingTab("liquidity", "流动性", "settings-grid", 50),
    ):
        app.register_tab(tab)
    app.register_setting(SettingDefinition(
        "engine",
        "回测引擎",
        "engine",
        "select",
        "native_event",
        ScopePolicy.SHARED_ONLY,
        SettingScope.SHARED,
        options=(
            SettingOption("native_batch", "GTHT 向量批量"),
            SettingOption("native_event", "GTHT 事件驱动"),
            SettingOption("backtrader", "Backtrader"),
            SettingOption("qlib", "Qlib"),
            SettingOption("zipline", "Zipline"),
        ),
        chip_template="引擎: {value}",
    ))
    app.register_setting(SettingDefinition(
        "factor_execution",
        "因子执行",
        "engine",
        "select",
        "incremental",
        ScopePolicy.SHARED_ONLY,
        SettingScope.SHARED,
        options=(
            SettingOption("batch", "先批量计算"),
            SettingOption("incremental", "随事件计算"),
        ),
        chip_template="因子: {value}",
    ))
    app.register_setting(SettingDefinition(
        "initial_capital",
        "初始资金",
        "capital",
        "number",
        100_000_000.0,
        ScopePolicy.SELECTABLE,
        SettingScope.SHARED,
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
        ScopePolicy.SELECTABLE,
        SettingScope.STRATEGY,
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
        ScopePolicy.SELECTABLE,
        SettingScope.STRATEGY,
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
        ScopePolicy.SELECTABLE,
        SettingScope.STRATEGY,
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
        ScopePolicy.SELECTABLE,
        SettingScope.STRATEGY,
        minimum=0.0,
        maximum=1.0,
        step=0.01,
        chip_template="参与率: {value}",
    ))
    return app


backtest_setting_registry = BacktestSettingRegistry()
backtest_setting_registry.register(group_test_settings())

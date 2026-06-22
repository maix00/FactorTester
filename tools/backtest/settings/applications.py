"""Built-in backtest application setting registrations."""

from __future__ import annotations

from .contracts import (
    ChipDefinition,
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
        SettingTab("factor", "因子执行", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 12),
        SettingTab(
            "time",
            "时间范围",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            15,
            summary_template="{start_date} {start_time} → {end_date} {end_time} · {timezone} · {time_precision}",
            summary_keys=("start_date", "start_time", "end_date", "end_time", "timezone", "time_precision"),
        ),
        SettingTab("capital", "资金", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 20),
        SettingTab("target_allocation", "目标分配", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 25),
        SettingTab("rebalance_trigger", "调仓触发", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 30),
        SettingTab("position_policy", "持仓政策", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 32),
        SettingTab("cost", "费用", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 40),
        SettingTab("order", "订单执行", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 45),
        SettingTab("liquidity", "流动性", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 50),
        SettingTab("margin", "保证金", (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS), "settings-grid", 55),
        SettingTab("market_rules", "市场规则", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 60),
        SettingTab("accounting", "记账规则", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 62),
        SettingTab("calendar", "回测时钟", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 65),
        SettingTab("evaluation", "样本划分", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 70),
    ):
        app.register_tab(tab)
    for chip in (
        ChipDefinition(
            "factor_alias",
            "因子",
            "identity",
            "{factorAlias}",
            ("factorAlias",),
            order=10,
            inherit_from_root=True,
        ),
        ChipDefinition(
            "tester",
            "测试器",
            "identity",
            "{testerLabel}",
            ("testerId",),
            order=20,
            inherit_from_root=True,
            value_resolvers={"testerLabel": "tester_label"},
            clickable=True,
        ),
        ChipDefinition(
            "group_index",
            "分组序号",
            "identity",
            "{groupIndex}/{splitCount}",
            ("groupIndex", "splitCount"),
            order=30,
            inherit_from_root=True,
        ),
        ChipDefinition(
            "product_mask",
            "品种范围",
            "derived",
            "📋 {productCount}品种 {expandSymbol}",
            ("productMask",),
            order=40,
            value_resolvers={
                "productCount": "product_mask_count",
                "expandSymbol": "product_mask_expand_symbol",
            },
            clickable=True,
        ),
    ):
        app.register_chip_field(chip)
    app.register_setting(SettingDefinition(
        "engine",
        "回测引擎",
        "engine",
        "select",
        "native",
        ScopePolicy.LOCAL_ONLY,
        options=(
            SettingOption("native", "Native 事件驱动回测工具"),
            SettingOption("backtrader", "Backtrader 事件驱动回测工具"),
            SettingOption("qlib", "Qlib 事件驱动回测工具"),
            SettingOption("zipline", "Zipline 事件驱动回测工具"),
        ),
        chip_template="引擎: {value}",
    ))
    app.register_setting(SettingDefinition(
        "factor_mode",
        "因子计算模式",
        "factor",
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
        "start_date", "开始日期", "time", "date", "", ScopePolicy.LOCAL_ONLY,
        chip_template="开始: {value}",
    ))
    app.register_setting(SettingDefinition(
        "end_date", "结束日期", "time", "date", "", ScopePolicy.LOCAL_ONLY,
        chip_template="结束: {value}",
    ))
    app.register_setting(SettingDefinition(
        "start_time", "开始时间", "time", "time", "00:00", ScopePolicy.LOCAL_ONLY,
        chip_template="开始时刻: {value}",
    ))
    app.register_setting(SettingDefinition(
        "end_time", "结束时间", "time", "time", "23:59", ScopePolicy.LOCAL_ONLY,
        chip_template="结束时刻: {value}",
    ))
    app.register_setting(SettingDefinition(
        "time_precision", "时间精度", "time", "select", "exact", ScopePolicy.LOCAL_ONLY,
        options=(SettingOption("exact", "精确时间"), SettingOption("day", "天级")),
        chip_template="精度: {value}",
    ))
    app.register_setting(SettingDefinition(
        "timezone", "时区", "time", "select", "Asia/Shanghai", ScopePolicy.LOCAL_ONLY,
        options=(
            SettingOption("Asia/Shanghai", "Asia/Shanghai (UTC+8)"),
            SettingOption("UTC", "UTC"),
            SettingOption("America/New_York", "America/New_York"),
            SettingOption("Europe/London", "Europe/London"),
        ),
        chip_template="时区: {value}",
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
        "base_currency", "基础货币", "capital", "select", "CNY", ScopePolicy.GROUP_OVERRIDE,
        options=(SettingOption("CNY", "CNY"), SettingOption("USD", "USD")),
        chip_template="币种: {value}",
    ))
    app.register_setting(SettingDefinition(
        "currency_conversion_fee_rate", "换汇佣金率", "capital", "number", 0.0,
        ScopePolicy.GROUP_OVERRIDE, minimum=0.0, step=0.000001,
    ))
    app.register_setting(SettingDefinition(
        "allocation_policy",
        "目标分配",
        "target_allocation",
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
        "target_allocation",
        "number",
        20,
        ScopePolicy.GROUP_OVERRIDE,
        minimum=2,
        step=1,
        chip_template="波动率窗口: {value}",
    ))
    app.register_setting(SettingDefinition(
        "volatility_warmup", "等风险预热处理", "target_allocation", "select", "equal_notional",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("equal_notional", "预热期使用等市值并记录"),
            SettingOption("error", "数据不足即报错"),
        ),
    ))
    app.register_setting(SettingDefinition(
        "rebalance_trigger",
        "触发规则",
        "rebalance_trigger",
        "select",
        "on_factor_signal",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("on_factor_signal", "因子信号事件"),
            SettingOption("membership_change", "成员变化事件"),
            SettingOption("scheduled", "日历计划事件"),
        ),
        chip_template="触发: {value}",
    ))
    app.register_setting(SettingDefinition(
        "position_policy",
        "仓位处理",
        "position_policy",
        "select",
        "rebalance_to_target",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("rebalance_to_target", "按目标调仓"),
            SettingOption("buy_and_hold", "买入持有"),
        ),
        chip_template="持仓: {value}",
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
        "custom_fee_rate", "自定义成交费率", "cost", "number", 0.0,
        ScopePolicy.GROUP_OVERRIDE, minimum=0.0, step=0.000001,
        chip_template="费率: {value}",
    ))
    app.register_setting(SettingDefinition(
        "slippage_mode", "滑点模型", "cost", "select", "none",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("none", "零滑点"),
            SettingOption("fixed_bps", "固定基点"),
        ),
        chip_template="滑点: {value}",
    ))
    app.register_setting(SettingDefinition(
        "slippage_bps", "固定滑点（基点）", "cost", "number", 0.0,
        ScopePolicy.GROUP_OVERRIDE, minimum=0.0, step=0.1,
        chip_template="滑点bp: {value}",
    ))
    app.register_setting(SettingDefinition(
        "order_type",
        "订单类型",
        "order",
        "select",
        "market",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("market", "市价单"),
            SettingOption("limit", "限价单"),
        ),
        chip_template="订单: {value}",
    ))
    app.register_setting(SettingDefinition(
        "matching_model",
        "撮合模型",
        "order",
        "select",
        "next_bar_full_fill",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("next_bar_full_fill", "下一 bar 全额成交"),
            SettingOption("bar_volume_limited", "按 bar 成交量限制"),
        ),
        chip_template="撮合: {value}",
    ))
    app.register_setting(SettingDefinition(
        "quantity_rounding_policy",
        "数量取整",
        "order",
        "select",
        "floor_to_lot",
        ScopePolicy.GROUP_OVERRIDE,
        options=(
            SettingOption("floor_to_lot", "按最小买入手数向下取整"),
            SettingOption("nearest_lot", "按最小买入手数四舍五入"),
        ),
        chip_template="取整: {value}",
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
        "margin_mode", "保证金约束", "margin", "select", "market",
        ScopePolicy.GROUP_OVERRIDE,
        options=(SettingOption("none", "关闭"), SettingOption("market", "市场保证金规则")),
        chip_template="保证金: {value}",
    ))
    app.register_setting(SettingDefinition(
        "collateral_fraction", "最大保证金占权益", "margin", "number", 1.0,
        ScopePolicy.GROUP_OVERRIDE, minimum=0.01, maximum=1.0, step=0.01,
        chip_template="保证金上限: {value}",
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
    app.register_setting(SettingDefinition(
        "money_unit_policy",
        "金额精度",
        "accounting",
        "select",
        "minor_units",
        ScopePolicy.LOCAL_ONLY,
        options=(
            SettingOption("minor_units", "内部按分制整数记账"),
            SettingOption("engine_native", "使用执行引擎原生金额精度"),
        ),
        chip_template="金额精度: {value}",
    ))
    app.register_setting(SettingDefinition(
        "evaluation_split",
        "样本内截止日期",
        "evaluation",
        "date",
        "",
        ScopePolicy.LOCAL_ONLY,
        chip_template="样本内截止: {value}",
        help_text="截止日期之后为样本外；留空表示全部为样本内。",
    ))
    app.register_setting(SettingDefinition(
        "calendar_frequency", "公共回测时钟", "calendar", "select", "auto",
        ScopePolicy.LOCAL_ONLY,
        options=(
            SettingOption("auto", "按因子频率自动判断"),
            SettingOption("1min", "1 分钟"),
            SettingOption("5min", "5 分钟"),
            SettingOption("1day", "1 天"),
        ),
        chip_template="时钟: {value}",
    ))
    return app


backtest_setting_registry = BacktestSettingRegistry()
backtest_setting_registry.register(group_test_settings())

"""Group-test (backtest) application settings.

Moved here from GroupTestModuleRegistry so the registry only deals with
module aggregation (build_group_params, collect_outputs, progress_manifest),
not application-level UI declarations.
"""

from __future__ import annotations

from typing import Any

from tools.testers.settings.contracts import (
    ChipDefinition,
    ScopePolicy,
    SettingDefinition,
    SettingModule,
    SettingOption,
    SettingTab,
    TabMountPoint,
)
from tools.testers.settings.applications import (
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTION_KEYS,
    MARKET_DATA_SELECTION_KEYS,
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTION_KEYS,
    RUN_WINDOW_KEYS,
    register_factor_candidate_list_base,
    register_factor_execution_base,
    register_factor_selection_base,
    register_market_data_base,
    register_product_path_candidate_list_base,
    register_product_path_selection_base,
    register_run_window_base,
)


def register_group_test_settings(app: Any) -> None:
    """Register all group_test infrastructure settings on an ApplicationSettings.

    Covers SettingModules, SettingTabs, ChipDefinitions, and non-module
    SettingDefinitions (engine, capital, allocation, rebalance, position,
    order execution, market rules, accounting, evaluation, calendar).

    Module-owned settings (fee, slippage, liquidity, margin) are registered
    separately by register_all_module_settings(app).
    """
    app.register_accepted_global_default_keys(
        *RUN_WINDOW_KEYS,
        *PRODUCT_PATH_CANDIDATE_KEYS,
        *PRODUCT_PATH_SELECTION_KEYS,
        *FACTOR_CANDIDATE_KEYS,
        *FACTOR_SELECTION_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
    )

    # ── SettingModules ──────────────────────────────────────
    for module in (
        SettingModule("execution_engine", "执行引擎", "backtest", 10),
        SettingModule("factor_execution", "因子执行", "factor", 20),
        SettingModule("product_selection", "品种/路径选择", "product", 30),
        SettingModule("market_data_source", "数据源", "market_data", 35),
        SettingModule("market_data_frequency", "数据频率", "market_data", 36),
        SettingModule("run_window", "运行时间范围", "backtest", 40),
        SettingModule("portfolio_capital", "组合资金", "portfolio", 50),
        SettingModule(
            "target_allocation", "目标分配", "strategy", 60,
            execution_stage="target_generation",
            sharing_scope="batch_market_state",
            trace_policy="target_trace",
            capabilities=("shared_volatility_estimation", "per_strategy_membership"),
        ),
        SettingModule("rebalance_trigger", "调仓触发", "strategy", 70),
        SettingModule("position_policy", "持仓政策", "strategy", 80),
        SettingModule("group_strategy", "分组策略", "strategy", 90),
        SettingModule(
            "transaction_cost", "交易费用", "execution", 100,
            execution_stage="order_fill_accounting",
            sharing_scope="per_strategy_ledger",
            trace_policy="execution_trace",
            capabilities=("fee_schedule", "close_today", "fifo_position_lots"),
        ),
        SettingModule("slippage", "滑点", "execution", 110),
        SettingModule("order_execution", "订单类型", "execution", 120),
        SettingModule("order_matching", "撮合", "execution", 130),
        SettingModule("order_sizing", "数量取整", "execution", 140),
        SettingModule(
            "liquidity", "流动性", "execution", 150,
            execution_stage="order_sizing",
            sharing_scope="batch_market_state",
            trace_policy="execution_trace",
            capabilities=("volume_participation",),
        ),
        SettingModule("margin", "保证金", "risk", 160),
        SettingModule("market_rules", "市场规则", "market_data", 170),
        SettingModule("accounting", "记账", "accounting", 180),
        SettingModule("backtest_calendar", "回测时钟", "backtest", 190),
        SettingModule("evaluation_range", "样本划分", "evaluation", 200),
    ):
        app.register_module(module)

    # ── SettingTabs ─────────────────────────────────────────
    for tab in (
        SettingTab("engine", "执行引擎", (TabMountPoint.LOCAL_SETTINGS,),
                   "settings-grid", 10, (TabMountPoint.LOCAL_SETTINGS,)),
        SettingTab("factor", "因子执行",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 12),
        SettingTab("product_path_selection", "产品路径",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 13),
        SettingTab("group_strategy", "分组数量",
                   (TabMountPoint.GROUP_SETTINGS,), "settings-grid", 14),
        SettingTab("data_source", "数据源",
                   (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 15),
        SettingTab("frequency", "数据频率",
                   (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 16),
        SettingTab("time", "时间范围",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 17,
                   summary_template="{start_date} → {end_date} · {time_precision}",
                   summary_keys=("start_date", "end_date", "time_precision")),
        SettingTab("capital", "资金",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 20),
        SettingTab("target_allocation", "目标分配",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 25),
        SettingTab("rebalance_trigger", "调仓触发",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 30),
        SettingTab("position_policy", "持仓政策",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 32),
        SettingTab("cost", "费用",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 40),
        SettingTab("order", "订单执行",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 45),
        SettingTab("liquidity", "流动性",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 50),
        SettingTab("margin", "保证金",
                   (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                   "settings-grid", 55),
        SettingTab("market_rules", "市场规则",
                   (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 60),
        SettingTab("accounting", "记账规则",
                   (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 62),
        SettingTab("calendar", "回测时钟",
                   (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 65),
        SettingTab("evaluation", "样本划分",
                   (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 70),
    ):
        app.register_tab(tab)

    # ── ChipDefinitions ─────────────────────────────────────
    for chip in (
        ChipDefinition("factor_alias", "因子", "identity",
                       "因子: {factorAlias}", ("factorAlias",),
                       module="factor_execution", order=10,
                       inherit_from_root=True, batch_owned=True),
        ChipDefinition("product_path_selection", "产品路径", "identity",
                       "产品路径: {productPathSelectionLabel}",
                       ("product_path_selection",),
                       module="product_selection", order=20,
                       inherit_from_root=True,
                       value_resolvers={"productPathSelectionLabel": "product_path_selection_label"},
                       clickable=True, batch_owned=True),
        ChipDefinition("split_count", "分组数", "identity",
                       "分组数: {splitCount}", ("splitCount",),
                       module="group_strategy", order=30,
                       inherit_from_root=True, batch_owned=True),
        ChipDefinition("group_index", "分组序号", "identity",
                       "分组序号: {groupIndex}", ("groupIndex",),
                       module="group_strategy", order=31,
                       inherit_from_root=True),
        ChipDefinition("product_mask", "品种范围", "derived",
                       "品种范围: {productCount}品种 {expandSymbol}",
                       ("productMask",),
                       module="product_selection", order=40,
                       value_resolvers={
                           "productCount": "product_mask_count",
                           "expandSymbol": "product_mask_expand_symbol",
                       },
                       clickable=True),
    ):
        app.register_chip_field(chip)

    # ── Infrastructure SettingDefinitions ──────────────────
    app.register_setting(SettingDefinition(
        "engine", "回测引擎", "engine", "select", "native",
        ScopePolicy.LOCAL_ONLY, module="execution_engine",
        options=(
            SettingOption("native", "Native 事件驱动回测工具"),
            SettingOption("backtrader", "Backtrader 事件驱动回测工具"),
            SettingOption("qlib", "Qlib 事件驱动回测工具"),
            SettingOption("zipline", "Zipline 事件驱动回测工具"),
            SettingOption("rqalpha", "RQAlpha 事件驱动回测工具"),
        ),
        chip_template="引擎: {value}",
    ))
    register_factor_execution_base(app)
    register_factor_candidate_list_base(app)
    register_factor_selection_base(app, scope_policy=ScopePolicy.GROUP_OVERRIDE)
    register_product_path_candidate_list_base(app)
    register_product_path_selection_base(app, scope_policy=ScopePolicy.GROUP_OVERRIDE)
    register_market_data_base(app, include_price_type=False)
    register_run_window_base(app, scope_policy=ScopePolicy.GROUP_OVERRIDE)

    app.register_setting(SettingDefinition(
        "splitCount", "分组数", "group_strategy", "number", 5,
        ScopePolicy.GROUP_ONLY, module="group_strategy",
        minimum=1, step=1, chip_template="分组数: {value}",
    ))
    app.register_setting(SettingDefinition(
        "groupIndex", "分组序号", "group_strategy", "number", 1,
        ScopePolicy.GROUP_ONLY, module="group_strategy",
        minimum=1, step=1, chip_template="分组序号: {value}",
    ))
    app.register_setting(SettingDefinition(
        "initial_capital", "初始资金", "capital", "number", 100_000_000.0,
        ScopePolicy.GROUP_OVERRIDE, module="portfolio_capital",
        minimum=0.01, step=10_000.0, chip_template="资金: {value}",
    ))
    app.register_setting(SettingDefinition(
        "base_currency", "基础货币", "capital", "select", "CNY",
        ScopePolicy.GROUP_OVERRIDE, module="portfolio_capital",
        options=(SettingOption("CNY", "CNY"), SettingOption("USD", "USD")),
        chip_template="币种: {value}",
    ))
    app.register_setting(SettingDefinition(
        "currency_conversion_fee_rate", "换汇佣金率", "capital", "number", 0.0,
        ScopePolicy.GROUP_OVERRIDE, module="portfolio_capital",
        minimum=0.0, step=0.000001,
    ))
    app.register_setting(SettingDefinition(
        "allocation_policy", "目标分配", "target_allocation", "select",
        "inverse_volatility", ScopePolicy.GROUP_OVERRIDE,
        module="target_allocation",
        options=(
            SettingOption("inverse_volatility", "等风险（波动率倒数）"),
            SettingOption("equal_notional", "等市值"),
            SettingOption("equal_margin", "等保证金（对照）"),
        ),
        chip_template="分配: {value}",
    ))
    app.register_setting(SettingDefinition(
        "volatility_lookback", "波动率回看期数", "target_allocation",
        "number", 20, ScopePolicy.GROUP_OVERRIDE,
        module="target_allocation", minimum=2, step=1,
        chip_template="波动率窗口: {value}",
        visible_when={"allocation_policy": ("inverse_volatility",)},
    ))
    app.register_setting(SettingDefinition(
        "volatility_warmup", "等风险预热处理", "target_allocation", "select",
        "equal_notional", ScopePolicy.GROUP_OVERRIDE,
        module="target_allocation",
        options=(
            SettingOption("equal_notional", "预热期使用等市值并记录"),
            SettingOption("error", "数据不足即报错"),
        ),
        visible_when={"allocation_policy": ("inverse_volatility",)},
    ))
    app.register_setting(SettingDefinition(
        "rebalance_trigger", "触发规则", "rebalance_trigger", "select",
        "on_factor_signal", ScopePolicy.GROUP_OVERRIDE,
        module="rebalance_trigger",
        options=(
            SettingOption("on_factor_signal", "因子信号事件"),
            SettingOption("membership_change", "成员变化事件"),
            SettingOption("scheduled", "日历计划事件"),
        ),
        chip_template="触发: {value}",
    ))
    app.register_setting(SettingDefinition(
        "position_policy", "仓位处理", "position_policy", "select",
        "rebalance_to_target", ScopePolicy.GROUP_OVERRIDE,
        module="position_policy",
        options=(
            SettingOption("rebalance_to_target", "按目标调仓"),
            SettingOption("buy_and_hold", "买入持有"),
        ),
        chip_template="持仓: {value}",
    ))
    app.register_setting(SettingDefinition(
        "execution_timing", "执行时点", "order", "select", "next_bar",
        ScopePolicy.GROUP_OVERRIDE, module="order_execution",
        options=(
            SettingOption("next_bar", "下一 bar 执行"),
            SettingOption("same_bar", "本 bar 执行"),
        ),
        chip_template="执行: {value}",
    ))
    app.register_setting(SettingDefinition(
        "execution_price_basis", "执行价格", "order", "select", "open",
        ScopePolicy.GROUP_OVERRIDE, module="order_execution",
        options=(
            SettingOption("close", "收盘/切片价格"),
            SettingOption("open", "开盘价"),
            SettingOption("vwap", "VWAP"),
        ),
        chip_template="价格: {value}",
    ))
    app.register_setting(SettingDefinition(
        "execution_delay_bars", "执行延迟 bar 数", "order", "number", 1,
        ScopePolicy.GROUP_OVERRIDE, module="order_execution",
        minimum=1, step=1,
        chip_template="延迟: {value} 根 bar",
        help_text="仅在「下一 bar 执行」时生效；1 表示信号产生后的下一根 bar 执行。",
        visible_when={"execution_timing": ("next_bar",)},
    ))
    app.register_setting(SettingDefinition(
        "order_type", "订单类型", "order", "select", "market",
        ScopePolicy.GROUP_OVERRIDE, module="order_execution",
        options=(
            SettingOption("market", "市价单"),
            SettingOption("limit", "限价单"),
        ),
        chip_template="订单: {value}",
    ))
    app.register_setting(SettingDefinition(
        "matching_model", "撮合模型", "order", "select", "next_bar_full_fill",
        ScopePolicy.GROUP_OVERRIDE, module="order_matching",
        options=(
            SettingOption("next_bar_full_fill", "下一 bar 全额成交"),
            SettingOption("bar_volume_limited", "按 bar 成交量限制"),
        ),
        chip_template="撮合: {value}",
    ))
    app.register_setting(SettingDefinition(
        "quantity_rounding_policy", "数量取整", "order", "select",
        "floor_to_lot", ScopePolicy.GROUP_OVERRIDE, module="order_sizing",
        options=(
            SettingOption("floor_to_lot", "按最小买入手数向下取整"),
            SettingOption("nearest_lot", "按最小买入手数四舍五入"),
        ),
        chip_template="取整: {value}",
    ))
    app.register_setting(SettingDefinition(
        "market_rule_fallback", "历史规则缺失处理", "market_rules",
        "select", "latest_available", ScopePolicy.LOCAL_ONLY,
        module="market_rules",
        options=(
            SettingOption("latest_available", "使用最新规则并标记近似"),
            SettingOption("strict_historical", "缺失即报错"),
            SettingOption("configured_default", "使用注册默认值并标记近似"),
        ),
        chip_template="规则回退: {value}",
    ))
    app.register_setting(SettingDefinition(
        "money_unit_policy", "金额精度", "accounting", "select",
        "minor_units", ScopePolicy.LOCAL_ONLY, module="accounting",
        options=(
            SettingOption("minor_units", "内部按分制整数记账"),
            SettingOption("engine_native", "使用执行引擎原生金额精度"),
        ),
        engine_defaults={"rqalpha": "engine_native"},
        disabled_values_by_engine={"rqalpha": ("minor_units",)},
        chip_template="金额精度: {value}",
    ))
    app.register_setting(SettingDefinition(
        "position_lot_policy", "持仓批次", "accounting", "select",
        "fifo", ScopePolicy.LOCAL_ONLY, module="accounting",
        options=(SettingOption("fifo", "FIFO 先进先出"),),
        chip_template="持仓批次: {value}",
        help_text="用于期货平仓、平今/平昨费用与实现盈亏归属的批次语义；当前通用期货账本按 FIFO 管理 lot。",
    ))
    app.register_setting(SettingDefinition(
        "evaluation_split", "样本内截止日期", "evaluation", "date", None,
        ScopePolicy.LOCAL_ONLY, module="evaluation_range",
        chip_template="样本内截止: {value}",
        help_text="截止日期之后为样本外；留空表示全部为样本内。",
    ))
    app.register_setting(SettingDefinition(
        "calendar_frequency", "公共回测时钟", "calendar", "select", "auto",
        ScopePolicy.LOCAL_ONLY, module="backtest_calendar",
        options=(
            SettingOption("auto", "按因子频率自动判断"),
            SettingOption("1min", "1 分钟"),
            SettingOption("5min", "5 分钟"),
            SettingOption("1day", "1 天"),
        ),
        chip_template="时钟: {value}",
    ))

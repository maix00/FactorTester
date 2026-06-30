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
    register_factor_selection_base,
    register_product_path_candidate_list_base,
    register_product_path_selection_base,
    register_run_window_base,
)


def register_group_test_settings(app: Any) -> None:
    """Register all group_test infrastructure settings on an ApplicationSettings.

    Covers SettingModules, ChipDefinitions, and non-module SettingDefinitions
    (engine, order execution, market rules, calendar). Tabs are materialized
    from the registered setting/FieldDefinition metadata instead of being
    maintained as a separate hardcoded list.

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
                       "分组数: {n_groups}", ("n_groups",),
                       module="group_strategy", order=30,
                       inherit_from_root=True, batch_owned=True),
        ChipDefinition("group_index", "分组序号", "identity",
                       "分组序号: {group_index}", ("group_index",),
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
        tab_label="执行引擎",
        tab_order=10,
        tab_default_mount_points=(TabMountPoint.LOCAL_SETTINGS,),
    ))
    # factor_mode: registered by FactorSignalModule (issue-114), not
    # register_factor_execution_base -- it directly selects which
    # signal_live/signal_precomputed Flow this strategy activates.
    register_factor_candidate_list_base(app, scope_policy=ScopePolicy.OVERRIDABLE)
    register_factor_selection_base(app, scope_policy=ScopePolicy.OVERRIDABLE)
    register_product_path_candidate_list_base(app, scope_policy=ScopePolicy.OVERRIDABLE)
    register_product_path_selection_base(app, scope_policy=ScopePolicy.OVERRIDABLE)
    # data_source/frequency: registered by MarketDataModule (issue-114) via
    # register_all_module_settings below, not register_market_data_base --
    # unlike product_path_selection/factor (resolved upstream by candidate-
    # list machinery this module only consumes), data_source/frequency have
    # no candidate-list/fallback metadata, so MarketDataModule is the real
    # owner here, not just a consumer.
    register_run_window_base(app, scope_policy=ScopePolicy.OVERRIDABLE)

    # splitCount/groupIndex/initial_capital/base_currency/allocation_policy/
    # volatility_lookback/volatility_warmup/rebalance_trigger/position_policy/
    # execution_timing/execution_delay_bars/quantity_rounding_policy/
    # money_unit_policy/position_lot_policy/evaluation_split — superseded by
    # the issue-114 ExecutableModule fields (LedgerModule.initial_capital_major/
    # base_currency, GroupMembershipModule.{n_groups,group_index,
    # allocation_policy,volatility_lookback,volatility_warmup,rebalance_trigger,
    # position_policy,execution_timing,execution_delay_bars},
    # PositionSizingModule.quantity_rounding_policy, MinorUnitModule.
    # use_minor_units, TradingRuleModule.cost_basis_method, RiskMetricsModule.
    # evaluation_split) — registered by register_all_module_settings(app)
    # below, not here. Removed rather than kept alongside to avoid two
    # parallel settings for the same concept.
    app.register_setting(SettingDefinition(
        "currency_conversion_fee_rate", "换汇佣金率", "capital", "number", 0.0,
        ScopePolicy.OVERRIDABLE, module="portfolio_capital",
        minimum=0.0, step=0.000001,
        chip_template="换汇费率: {value}",
        tab_label="资金",
        tab_order=50,
    ))
    app.register_setting(SettingDefinition(
        "execution_price_basis", "执行价格", "order", "select", "open",
        ScopePolicy.OVERRIDABLE, module="order_execution",
        options=(
            SettingOption("close", "收盘/切片价格"),
            SettingOption("open", "开盘价"),
            SettingOption("vwap", "VWAP"),
        ),
        chip_template="价格: {value}",
        tab_label="订单执行",
        tab_order=120,
    ))
    app.register_setting(SettingDefinition(
        "order_type", "订单类型", "order", "select", "market",
        ScopePolicy.OVERRIDABLE, module="order_execution",
        options=(
            SettingOption("market", "市价单"),
            SettingOption("limit", "限价单"),
        ),
        chip_template="订单: {value}",
        tab_label="订单执行",
        tab_order=120,
    ))
    app.register_setting(SettingDefinition(
        "matching_model", "撮合模型", "order", "select", "next_bar_full_fill",
        ScopePolicy.OVERRIDABLE, module="order_matching",
        options=(
            SettingOption("next_bar_full_fill", "下一 bar 全额成交"),
            SettingOption("bar_volume_limited", "按 bar 成交量限制"),
        ),
        chip_template="撮合: {value}",
        tab_label="订单执行",
        tab_order=120,
    ))
    app.register_setting(SettingDefinition(
        "market_rule_fallback", "历史规则缺失处理", "market_rules",
        "select", "latest_available", ScopePolicy.OVERRIDABLE,
        module="market_rules",
        options=(
            SettingOption("latest_available", "使用最新规则并标记近似"),
            SettingOption("strict_historical", "缺失即报错"),
            SettingOption("configured_default", "使用注册默认值并标记近似"),
        ),
        chip_template="规则回退: {value}",
        tab_label="市场规则",
        tab_order=170,
    ))
    app.register_setting(SettingDefinition(
        "calendar_frequency", "公共回测时钟", "calendar", "select", "auto",
        ScopePolicy.OVERRIDABLE, module="backtest_calendar",
        options=(
            SettingOption("auto", "按因子频率自动判断"),
            SettingOption("1min", "1 分钟"),
            SettingOption("5min", "5 分钟"),
            SettingOption("1day", "1 天"),
        ),
        chip_template="时钟: {value}",
        tab_label="回测时钟",
        tab_order=190,
    ))

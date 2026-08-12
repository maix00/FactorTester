"""Group-test (backtest) application settings.

Moved here from GroupTestModuleRegistry so the registry only deals with
module aggregation (build_group_params, collect_outputs, progress_manifest),
not application-level UI declarations.
"""

from __future__ import annotations

from typing import Any

from tools.testers.settings.contracts import ChipDefinition, SettingModule
from tools.testers.settings.applications import (
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTION_KEYS,
    MARKET_DATA_SELECTION_KEYS,
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTION_KEYS,
    RUN_WINDOW_KEYS,
)
from tools.testers._shared.factor import FACTOR_SOURCE_KEYS
from tools.testers._shared.template import register_test_template_base


def register_group_test_settings(app: Any) -> None:
    """Register all group_test infrastructure settings on an ApplicationSettings.

    Covers SettingModules and ChipDefinitions. User-editable controls are
    registered from ExecutableModule FieldDefinitions by
    register_all_module_settings(app).
    """
    app.register_accepted_global_default_keys(
        *RUN_WINDOW_KEYS,
        *PRODUCT_PATH_CANDIDATE_KEYS,
        *PRODUCT_PATH_SELECTION_KEYS,
        *FACTOR_CANDIDATE_KEYS,
        *FACTOR_SELECTION_KEYS,
        *FACTOR_SOURCE_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
    )
    register_test_template_base(app)

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
        SettingModule("order_sizing", "数量取整", "execution", 140),
        SettingModule(
            "volume_capacity", "成交量容量", "execution", 150,
            execution_stage="order_sizing",
            sharing_scope="batch_market_state",
            trace_policy="execution_trace",
            capabilities=("volume_participation",),
        ),
        SettingModule("margin", "保证金", "risk", 160),
        SettingModule("accounting", "记账", "accounting", 180),
    ):
        app.register_module(module)

    # ── ChipDefinitions ─────────────────────────────────────
    for chip in (
        ChipDefinition("factor_alias", "因子", "identity",
                       "因子: {factorAlias}", ("factorAlias",),
                       module="factor_execution", target_tab="factor", order=10,
                       inherit_from_root=True, batch_owned=True,
                       source_adapter="selected_factors"),
        ChipDefinition("product_path_selection", "产品路径", "identity",
                       "产品路径: {productPathSelectionLabel}",
                       ("product_path_selection",),
                       module="product_selection", target_tab="product_path_selection", order=20,
                       inherit_from_root=True,
                       value_resolvers={"productPathSelectionLabel": "product_path_selection_label"},
                       clickable=True, batch_owned=True,
                       source_adapter="selected_product_paths"),
        ChipDefinition("split_count", "分组数", "identity",
                       "分组数: {n_groups}", ("n_groups",),
                       module="group_strategy", target_tab="group_strategy", order=30,
                       inherit_from_root=True, batch_owned=True,
                       source_adapter="primary_strategy_group"),
        ChipDefinition("group_index", "分组序号", "identity",
                       "分组序号: {group_index}", ("group_index",),
                       module="group_strategy", target_tab="group_strategy", order=31,
                       inherit_from_root=True,
                       source_adapter="primary_strategy_group"),
        ChipDefinition("product_mask", "品种范围", "derived",
                       "品种范围: {productCount}品种 {expandSymbol}",
                       ("productMask",),
                       module="product_selection", target_tab="product_path_selection", order=40,
                       value_resolvers={
                           "productCount": "product_mask_count",
                           "expandSymbol": "product_mask_expand_symbol",
                       },
                       clickable=True,
                       source_adapter="primary_strategy_group"),
    ):
        app.register_chip_field(chip)

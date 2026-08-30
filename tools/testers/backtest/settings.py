"""Group-test (backtest) application settings.

Moved here from GroupTestModuleRegistry so the registry only deals with
module aggregation (build_group_params, collect_outputs, progress_manifest),
not application-level UI declarations.
"""

from __future__ import annotations

from typing import Any

from tools.testers._shared.category import (
    CATEGORY_CANDIDATE_KEYS,
    CATEGORY_SELECTION_KEYS,
)
from tools.testers._shared.factor import FACTOR_SOURCE_SELECTION_KEYS
from tools.testers._shared.run_inputs import register_run_inputs_base
from tools.testers._shared.scope_chips import register_factor_product_scope_chips
from tools.testers._shared.template import register_test_template_base
from tools.testers.settings.applications import (
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTION_KEYS,
    MARKET_DATA_SELECTION_KEYS,
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTION_KEYS,
    RUN_WINDOW_KEYS,
)
from tools.testers.settings.contracts import (
    ChipDefinition,
    SettingModule,
    SettingsSection,
)


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
        *FACTOR_SOURCE_SELECTION_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
        *CATEGORY_CANDIDATE_KEYS,
        *CATEGORY_SELECTION_KEYS,
    )
    register_test_template_base(app)
    register_run_inputs_base(app)
    app.register_manifest_extension(
        "configuration_item_contract",
        {
            "schema_version": 1,
            "item_kind": "strategy",
            "collection_key": "groups",
            "min_items": 1,
            "create_template": {
                "id": "<unique-strategy-id>",
                "batchId": "<shared-addition-batch-id>",
                "name": "<strategy-name>",
                "factor_candidate_refs": ["<factor-ref>"],
                "product_path_selection": {
                    "product_path_selection_id": "<product-group-ref>",
                },
                "splitCount": 5,
                "groupIndex": 1,
            },
            "field_sources": {
                "factor_candidate_refs": "field:factor_candidates",
                "product_path_selection": "field:product_path_selection",
            },
            "batch_contract": {
                "identity_field": "batchId",
                "semantics": "one_addition_event",
                "shared_for_partition_members": True,
                "partition_fields": ["splitCount", "groupIndex"],
                "instruction": (
                    "Strategies created as the members of one N-group partition "
                    "must share one batchId; vary groupIndex from 1 through splitCount."
                ),
            },
            "schema": {
                "type": "object",
                "required": [
                    "id", "batchId", "name", "factor_candidate_refs", "product_path_selection",
                    "splitCount", "groupIndex",
                ],
                "properties": {
                    "id": {"type": "string", "minLength": 1, "title": "策略 ID"},
                    "batchId": {
                        "type": "string", "minLength": 1, "title": "添加批次 ID",
                    },
                    "name": {"type": "string", "minLength": 1, "title": "策略名称"},
                    "factor_candidate_refs": {
                        "type": "array", "minItems": 1, "title": "因子候选",
                        "items": {
                            "type": "string",
                            "pattern": r"factor:v2:[A-Za-z0-9_-]{43}",
                        },
                    },
                    "product_path_selection": {
                        "type": "object", "title": "产品组",
                    },
                    "splitCount": {
                        "type": "integer", "minimum": 1, "title": "分组数",
                    },
                    "groupIndex": {
                        "type": "integer", "minimum": 1, "title": "分组序号",
                    },
                },
            },
        },
    )
    _register_sections(app)

    # ── SettingModules ──────────────────────────────────────
    for module in (
        SettingModule("execution_engine", "执行引擎", "backtest", 10),
        SettingModule("factor_execution", "因子执行", "factor", 20),
        SettingModule("category_grouping", "分类分组", "product", 25),
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

    _register_category_selection(app)

    # ── ChipDefinitions ─────────────────────────────────────
    register_factor_product_scope_chips(app)
    for chip in (
        ChipDefinition("split_count", "分组数", "identity",
                       "分组数: {n_groups}", ("n_groups",),
                       module="group_strategy", target_tab="group_strategy", order=30,
                       inherit_from_root=True, batch_owned=True,
                       source_adapter="primary_strategy_group",
                       display_scope="strategy"),
        ChipDefinition("group_index", "分组序号", "identity",
                       "分组序号: {group_index}", ("group_index",),
                       module="group_strategy", target_tab="group_strategy", order=31,
                       inherit_from_root=True,
                       source_adapter="primary_strategy_group",
                       display_scope="strategy"),
    ):
        app.register_chip_field(chip)


def _register_sections(app: Any) -> None:
    """Group the long backtest form while leaving field ownership in modules."""
    for section in (
        SettingsSection(
            "authoring", "配置与模板",
            "先加载或保存模板，再开始本次回测配置", 10,
        ),
        SettingsSection(
            "scope", "研究对象与样本",
            "选择因子、产品路径、数据源和样本时间，确定回测研究范围", 20,
        ),
        SettingsSection(
            "portfolio", "组合与策略",
            "定义目标权重、调仓、持仓、分组和期限结构策略", 30,
        ),
        SettingsSection(
            "execution", "交易与执行",
            "设置引擎、合约生命周期、费用、订单和成交量容量", 40,
        ),
        SettingsSection(
            "risk", "资金与风险",
            "设置资金、保证金、记账和风险边界", 50,
        ),
        SettingsSection(
            "inputs", "运行输入",
            "策略 Hook、附加源码和运行时输入会随 Job 一起冻结", 60,
        ),
    ):
        app.register_settings_section(section)
    for section, tabs in {
        "authoring": ("test_template",),
        "scope": (
            "factor", "category", "product_path_selection", "data_source",
            "frequency", "time",
        ),
        "portfolio": (
            "target_allocation", "rebalance_trigger", "position_policy",
            "term_carry_strategy", "group_strategy", "strategy_book",
        ),
        "execution": (
            "engine", "delivery_force_close", "rollover", "cost", "order",
            "volume_capacity",
        ),
        "risk": ("capital", "margin", "accounting"),
        "inputs": ("run_inputs", "calendar"),
    }.items():
        for tab in tabs:
            app.set_tab_section(tab, section)


def _register_category_selection(app: Any) -> None:
    """Make the category catalog available to backtest product-group editors.

    Categories are authoring inputs for product-group path resolution rather
    than a hidden special case inside the product-group picker.  The tab is
    deliberately not mounted by default; a user can mount it before creating
    a product group in the same test workspace.
    """
    from tools.testers._shared.category import (
        register_category_candidate_list_base,
        register_category_selection_base,
    )
    from tools.testers.settings.contracts import SettingTab, TabMountPoint

    app.register_tab(SettingTab(
        "category", "分类", (TabMountPoint.LOCAL_SETTINGS,), "custom", 15,
        content_adapter="category_selection",
    ))
    register_category_candidate_list_base(app)
    register_category_selection_base(app)

"""Built-in backtest application setting registrations."""

from __future__ import annotations

from .contracts import (
    ChipDefinition,
    ResultTabDefinition,
    ScopePolicy,
    SettingDefinition,
    SettingModule,
    SettingOption,
    SettingsSurface,
    SettingTab,
    SurfaceFlow,
    TabMountPoint,
)
from .registry import ApplicationSettings, BacktestSettingRegistry

RUN_WINDOW_KEYS = (
    "start_date",
    "end_date",
    "start_time",
    "end_time",
    "timezone",
    "time_precision",
)
PRODUCT_PATH_SELECTION_KEYS = ("product_path_selection",)
PRODUCT_PATH_SELECTIONS_KEYS = ("product_path_selections",)
PRODUCT_PATH_CANDIDATE_KEYS = ("product_path_candidates",)
FACTOR_SELECTION_KEYS = ("factor",)
FACTOR_SELECTIONS_KEYS = ("factor_selections",)
FACTOR_CANDIDATE_KEYS = ("factor_candidates",)
MARKET_DATA_SELECTION_KEYS = ("data_source", "frequency")


def register_factor_execution_base(app: ApplicationSettings, *, tab: str = "factor") -> None:
    app.register_setting(SettingDefinition(
        "factor_mode",
        "因子计算模式",
        tab,
        "select",
        "auto",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
        options=(
            SettingOption("auto", "自动选择"),
            SettingOption("precomputed", "预计算后按事件回放"),
            SettingOption("incremental", "随事件增量计算"),
        ),
        chip_template="因子计算: {value}",
    ))


def register_run_window_base(
    app: ApplicationSettings,
    *,
    tab: str = "time",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "start_date", "开始日期", tab, "date", "", scope_policy,
        module="run_window", chip_template="开始日期: {value}",
        serialization={"display_order": 10},
    ))
    app.register_setting(SettingDefinition(
        "end_date", "结束日期", tab, "date", "", scope_policy,
        module="run_window", chip_template="结束日期: {value}",
        serialization={"display_order": 20},
    ))
    app.register_setting(SettingDefinition(
        "start_time", "开始时间", tab, "time", "00:00", scope_policy,
        module="run_window", chip_template="开始时间: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 40},
    ))
    app.register_setting(SettingDefinition(
        "end_time", "结束时间", tab, "time", "23:59", scope_policy,
        module="run_window", chip_template="结束时间: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 50},
    ))
    app.register_setting(SettingDefinition(
        "time_precision", "时间精度", tab, "select", "exact", scope_policy,
        module="run_window",
        options=(
            SettingOption("exact", "精确时间"),
            SettingOption("trading_day", "交易日"),
        ),
        chip_template="时间精度: {value}",
        serialization={"display_order": 30},
    ))
    app.register_setting(SettingDefinition(
        "timezone", "时区", tab, "select", "Asia/Shanghai", scope_policy,
        module="run_window",
        options=(
            SettingOption("Asia/Shanghai", "Asia/Shanghai (UTC+8)"),
            SettingOption("UTC", "UTC"),
            SettingOption("America/New_York", "America/New_York"),
            SettingOption("Europe/London", "Europe/London"),
        ),
        chip_template="时区: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 60},
    ))


def register_product_path_selection_base(
    app: ApplicationSettings,
    *,
    tab: str = "product_path_selection",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "product_path_selection",
        "产品路径",
        tab,
        "select",
        None,
        scope_policy,
        module="product_selection",
        chip_template="产品路径: {value}",
        help_text="选择或内联一组产品路径；若引用用户产品组模板，则保存产品组模板 id。",
        serialization={
            "kind": "product_path_selection",
            "display_order": 20,
            # 模块内单选为空时回退到页面共享的 product_path_selection。
            "shared_page_field": "product_path_selection",
            "product_group_reference_keys": (
                "product_group_template_id",
                "path_id",
            ),
            "product_group_source_type": "user_product_group_template",
            "id_keys": (
                "product_path_selection_id",
                "selection_id",
                "id",
            ),
            "manual_path_keys": (
                "paths",
                "selected_paths",
            ),
            "product_group_fields": (
                "product_path_selection_id",
            ),
            "manual_fields": (
                "product_path_selection_id",
                "paths",
            ),
        },
    ))


def register_product_path_selections_base(
    app: ApplicationSettings,
    *,
    tab: str = "product_path_selection",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "product_path_selections",
        "产品路径选择",
        tab,
        "custom",
        [],
        scope_policy,
        module="product_selection",
        chip_template="产品路径选择: {value}",
        help_text="从产品路径候选列表多选；为空时回退到候选列表（先本模块本地候选，再页面全局候选）。",
        serialization={
            "kind": "product_path_selection_list",
            "display_order": 30,
            "item_kind": "product_path_selection",
            "multi": True,
            "candidate_field": "product_path_candidates",
            # 多选为空时回退到候选列表本身：先本地 candidate_field，再其页面全局候选
            # （由 product_path_candidate_list 的 fallback_policy 声明 local→global）。
            "fallback": "candidates",
            "id_keys": (
                "product_path_selection_id",
                "selection_id",
                "id",
            ),
        },
    ))


def register_product_path_candidate_list_base(
    app: ApplicationSettings,
    *,
    tab: str = "product_path_selection",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "product_path_candidates",
        "产品路径候选列表",
        tab,
        "custom",
        [],
        scope_policy,
        module="product_selection",
        chip_template="产品路径候选: {value}",
        help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场路径组。",
        serialization={
            "kind": "product_path_candidate_list",
            "display_order": 10,
            "item_kind": "product_path_selection",
            "shared_page_field": "product_path_candidates",
            "selection_field": "product_path_selection",
            "product_group_source": "user_product_group_templates",
            "manual_candidate_source": "runtime_manual_path_group",
            "fallback_policy": (
                "copy_page_candidates",
                "load_user_product_groups_when_page_empty",
            ),
            "mutation_scope": {
                "page": "page_candidates_only",
                "module": "module_candidates_only",
            },
            "persist_manual_candidates": False,
            "dedupe_product_groups": True,
            "allow_duplicate_manual_candidates": True,
        },
    ))


def register_factor_candidate_list_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "factor_candidates",
        "因子候选列表",
        tab,
        "custom",
        [],
        scope_policy,
        module="factor_execution",
        chip_template="因子候选: {value}",
        help_text="页面级候选列表是共享资源；测试模块复制后可在本模块内追加现场因子。",
        serialization={
            "kind": "factor_candidate_list",
            "display_order": 10,
            "item_kind": "factor",
            "shared_page_field": "factor_candidates",
            "selection_field": "factor",
            "factor_library_source": "user_param_factor_overview",
            "fallback_policy": (
                "copy_page_candidates",
                "load_factor_library_when_page_empty",
            ),
            "id_keys": ("alias", "name", "factor_alias"),
            "label_keys": ("alias", "name", "label"),
            "mutation_scope": {
                "page": "page_candidates_only",
                "module": "module_candidates_only",
            },
        },
    ))


def register_factor_selection_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "factor",
        "因子",
        tab,
        "select",
        "",
        scope_policy,
        module="factor_execution",
        chip_template="因子: {value}",
        serialization={
            "kind": "factor_selection",
            "display_order": 20,
            "candidate_field": "factor_candidates",
            # 模块内单选为空时回退到页面共享的 factor。
            "shared_page_field": "factor",
            "id_keys": ("alias", "name", "factor_alias"),
            "label_keys": ("alias", "name", "label"),
        },
    ))


def register_factor_selections_base(
    app: ApplicationSettings,
    *,
    tab: str = "factor",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "factor_selections",
        "因子选择",
        tab,
        "custom",
        [],
        scope_policy,
        module="factor_execution",
        chip_template="因子选择: {value}",
        help_text="从因子候选列表多选；为空时回退到候选列表（先本模块本地候选，再页面全局候选）。",
        serialization={
            "kind": "factor_selection_list",
            "display_order": 30,
            "item_kind": "factor",
            "multi": True,
            "candidate_field": "factor_candidates",
            # 多选为空时回退到候选列表本身：先本地 candidate_field，再其页面全局候选
            # （由 factor_candidate_list 的 fallback_policy 声明 local→global）。
            "fallback": "candidates",
            "id_keys": ("alias", "name", "factor_alias"),
            "label_keys": ("alias", "name", "label"),
        },
    ))


def register_market_data_base(app: ApplicationSettings, *, include_price_type: bool) -> None:
    app.register_setting(SettingDefinition(
        "data_source",
        "数据源",
        "data_source",
        "select",
        "",
        ScopePolicy.LOCAL_ONLY,
        module="market_data_source",
        options=(SettingOption("", "自动"),),
        chip_template="数据源: {value}",
        serialization={"display_order": 10},
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


def single_factor_page_settings() -> ApplicationSettings:
    app = ApplicationSettings("single_factor_page")
    app.register_accepted_global_default_keys(*FACTOR_CANDIDATE_KEYS, *FACTOR_SELECTION_KEYS, *PRODUCT_PATH_CANDIDATE_KEYS, *PRODUCT_PATH_SELECTION_KEYS, *MARKET_DATA_SELECTION_KEYS, *RUN_WINDOW_KEYS)
    for module in (
        SettingModule("setting_template", "因子家族设置模板", "page", 10),
        SettingModule("factor_execution", "因子设置", "factor", 20),
        SettingModule("product_selection", "产品路径", "product", 30),
        SettingModule("market_data_source", "数据源", "market_data", 40),
        SettingModule("market_data_frequency", "数据频率", "market_data", 50),
        SettingModule("run_window", "时间范围", "time", 60),
    ):
        app.register_module(module)
    for tab in (
        SettingTab(
            "setting_template",
            "模板",
            (TabMountPoint.LOCAL_SETTINGS,),
            "custom",
            10,
            (TabMountPoint.LOCAL_SETTINGS,),
        ),
        SettingTab(
            "factors",
            "因子",
            (TabMountPoint.LOCAL_SETTINGS,),
            "custom",
            20,
            # 默认隐藏：加载模板后若含因子设置再懒挂载（见 main_page_settings_panel）。
        ),
        SettingTab(
            "product_path_selection",
            "产品路径",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            30,
        ),
        SettingTab(
            "data_source",
            "数据源",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            40,
        ),
        SettingTab(
            "frequency",
            "数据频率",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            50,
        ),
        SettingTab(
            "time",
            "时间范围",
            (TabMountPoint.LOCAL_SETTINGS,),
            "custom",
            60,
            summary_template="{start_date} → {end_date} · {time_precision}",
            summary_keys=("start_date", "end_date", "time_precision"),
        ),
    ):
        app.register_tab(tab)
    app.register_setting(SettingDefinition(
        "setting_template",
        "因子家族设置模板",
        "setting_template",
        "custom",
        None,
        ScopePolicy.LOCAL_ONLY,
        module="setting_template",
        chip_template="模板: {value}",
    ))
    register_factor_candidate_list_base(app, tab="factors")
    register_factor_selection_base(app, tab="factors")
    register_product_path_candidate_list_base(app)
    register_product_path_selection_base(app)
    register_market_data_base(app, include_price_type=False)
    register_run_window_base(app)
    # 单因子页只有"因子家族测试设置"这一个扁平面板（无列表项）。
    app.register_surface(SettingsSurface(
        "local", "因子家族测试设置", TabMountPoint.LOCAL_SETTINGS, kind="panel", order=10,
    ))
    return app


def group_test_settings() -> ApplicationSettings:
    app = ApplicationSettings("group_test")
    app.register_accepted_global_default_keys(*RUN_WINDOW_KEYS, *PRODUCT_PATH_CANDIDATE_KEYS, *PRODUCT_PATH_SELECTION_KEYS, *FACTOR_CANDIDATE_KEYS, *FACTOR_SELECTION_KEYS, *MARKET_DATA_SELECTION_KEYS)
    for module in (
        SettingModule("execution_engine", "执行引擎", "backtest", 10),
        SettingModule("factor_execution", "因子执行", "factor", 20),
        SettingModule("product_selection", "品种/路径选择", "product", 30),
        SettingModule("market_data_source", "数据源", "market_data", 35),
        SettingModule("market_data_frequency", "数据频率", "market_data", 36),
        SettingModule("run_window", "运行时间范围", "backtest", 40),
        SettingModule("portfolio_capital", "组合资金", "portfolio", 50),
        SettingModule(
            "target_allocation",
            "目标分配",
            "strategy",
            60,
            execution_stage="target_generation",
            sharing_scope="batch_market_state",
            trace_policy="target_trace",
            capabilities=("shared_volatility_estimation", "per_strategy_membership"),
        ),
        SettingModule("rebalance_trigger", "调仓触发", "strategy", 70),
        SettingModule("position_policy", "持仓政策", "strategy", 80),
        SettingModule("group_strategy", "分组策略", "strategy", 90),
        SettingModule(
            "transaction_cost",
            "交易费用",
            "execution",
            100,
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
            "liquidity",
            "流动性",
            "execution",
            150,
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
    for tab in (
        SettingTab(
            "engine", "执行引擎", (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid", 10, (TabMountPoint.LOCAL_SETTINGS,),
        ),
        SettingTab(
            "factor",
            "因子执行",
            (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
            "settings-grid",
            12,
        ),
        SettingTab(
            "product_path_selection",
            "产品路径",
            (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
            "settings-grid",
            13,
        ),
        SettingTab(
            "group_strategy",
            "分组数量",
            (TabMountPoint.GROUP_SETTINGS,),
            "settings-grid",
            14,
        ),
        SettingTab("data_source", "数据源", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 15),
        SettingTab("frequency", "数据频率", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 16),
        SettingTab(
            "time",
            "时间范围",
            (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
            "settings-grid",
            17,
            summary_template="{start_date} → {end_date} · {time_precision}",
            summary_keys=("start_date", "end_date", "time_precision"),
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
            "因子: {factorAlias}",
            ("factorAlias",),
            module="factor_execution",
            order=10,
            inherit_from_root=True,
        ),
        ChipDefinition(
            "product_path_selection",
            "产品路径",
            "identity",
            "产品路径: {productPathSelectionLabel}",
            ("product_path_selection",),
            module="product_selection",
            order=20,
            inherit_from_root=True,
            value_resolvers={"productPathSelectionLabel": "product_path_selection_label"},
            clickable=True,
        ),
        ChipDefinition(
            "split_count",
            "分组数",
            "identity",
            "分组数: {splitCount}",
            ("splitCount",),
            module="group_strategy",
            order=30,
            inherit_from_root=True,
        ),
        ChipDefinition(
            "group_index",
            "分组序号",
            "identity",
            "分组序号: {groupIndex}",
            ("groupIndex",),
            module="group_strategy",
            order=31,
            inherit_from_root=True,
        ),
        ChipDefinition(
            "product_mask",
            "品种范围",
            "derived",
            "品种范围: {productCount}品种 {expandSymbol}",
            ("productMask",),
            module="product_selection",
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
        module="execution_engine",
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
        "splitCount",
        "分组数",
        "group_strategy",
        "number",
        5,
        ScopePolicy.GROUP_ONLY,
        module="group_strategy",
        minimum=1,
        step=1,
        chip_template="分组数: {value}",
    ))
    app.register_setting(SettingDefinition(
        "groupIndex",
        "分组序号",
        "group_strategy",
        "number",
        1,
        ScopePolicy.GROUP_ONLY,
        module="group_strategy",
        minimum=1,
        step=1,
        chip_template="分组序号: {value}",
    ))
    app.register_setting(SettingDefinition(
        "initial_capital",
        "初始资金",
        "capital",
        "number",
        100_000_000.0,
        ScopePolicy.GROUP_OVERRIDE,
        module="portfolio_capital",
        minimum=0.01,
        step=10_000.0,
        chip_template="资金: {value}",
    ))
    app.register_setting(SettingDefinition(
        "base_currency", "基础货币", "capital", "select", "CNY", ScopePolicy.GROUP_OVERRIDE,
        module="portfolio_capital",
        options=(SettingOption("CNY", "CNY"), SettingOption("USD", "USD")),
        chip_template="币种: {value}",
    ))
    app.register_setting(SettingDefinition(
        "currency_conversion_fee_rate", "换汇佣金率", "capital", "number", 0.0,
        ScopePolicy.GROUP_OVERRIDE, module="portfolio_capital", minimum=0.0, step=0.000001,
    ))
    app.register_setting(SettingDefinition(
        "allocation_policy",
        "目标分配",
        "target_allocation",
        "select",
        "inverse_volatility",
        ScopePolicy.GROUP_OVERRIDE,
        module="target_allocation",
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
        module="target_allocation",
        minimum=2,
        step=1,
        chip_template="波动率窗口: {value}",
        visible_when={"allocation_policy": ("inverse_volatility",)},
    ))
    app.register_setting(SettingDefinition(
        "volatility_warmup", "等风险预热处理", "target_allocation", "select", "equal_notional",
        ScopePolicy.GROUP_OVERRIDE,
        module="target_allocation",
        options=(
            SettingOption("equal_notional", "预热期使用等市值并记录"),
            SettingOption("error", "数据不足即报错"),
        ),
        visible_when={"allocation_policy": ("inverse_volatility",)},
    ))
    app.register_setting(SettingDefinition(
        "rebalance_trigger",
        "触发规则",
        "rebalance_trigger",
        "select",
        "on_factor_signal",
        ScopePolicy.GROUP_OVERRIDE,
        module="rebalance_trigger",
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
        module="position_policy",
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
        module="transaction_cost",
        options=(
            SettingOption("none", "无费用"),
            SettingOption("market", "市场历史费率"),
            SettingOption("custom", "自定义费率"),
        ),
        chip_template="费用: {value}",
    ))
    app.register_setting(SettingDefinition(
        "custom_fee_rate", "自定义成交费率", "cost", "number", 0.0,
        ScopePolicy.GROUP_OVERRIDE, module="transaction_cost", minimum=0.0, step=0.000001,
        chip_template="费率: {value}",
        visible_when={"fee_mode": ("custom",)},
    ))
    app.register_setting(SettingDefinition(
        "slippage_mode", "滑点模型", "cost", "select", "none",
        ScopePolicy.GROUP_OVERRIDE,
        module="slippage",
        options=(
            SettingOption("none", "零滑点"),
            SettingOption("fixed_bps", "固定基点"),
        ),
        chip_template="滑点: {value}",
    ))
    app.register_setting(SettingDefinition(
        "slippage_bps", "固定滑点（基点）", "cost", "number", 0.0,
        ScopePolicy.GROUP_OVERRIDE, module="slippage", minimum=0.0, step=0.1,
        chip_template="滑点bp: {value}",
        visible_when={"slippage_mode": ("fixed_bps",)},
    ))
    app.register_setting(SettingDefinition(
        "execution_timing",
        "执行时点",
        "order",
        "select",
        "next_bar",
        ScopePolicy.GROUP_OVERRIDE,
        module="order_execution",
        options=(
            SettingOption("next_bar", "下一 bar 执行"),
            SettingOption("same_bar", "本 bar 执行"),
        ),
        chip_template="执行: {value}",
    ))
    app.register_setting(SettingDefinition(
        "execution_price_basis",
        "执行价格",
        "order",
        "select",
        "open",
        ScopePolicy.GROUP_OVERRIDE,
        module="order_execution",
        options=(
            SettingOption("close", "收盘/切片价格"),
            SettingOption("open", "开盘价"),
            SettingOption("vwap", "VWAP"),
        ),
        chip_template="价格: {value}",
    ))
    app.register_setting(SettingDefinition(
        "execution_delay_bars",
        "执行延迟 bar 数",
        "order",
        "number",
        1,
        ScopePolicy.GROUP_OVERRIDE,
        module="order_execution",
        minimum=1,
        step=1,
        chip_template="延迟: {value} 根 bar",
        help_text="仅在“下一 bar 执行”时生效；1 表示信号产生后的下一根 bar 执行。",
        visible_when={"execution_timing": ("next_bar",)},
    ))
    app.register_setting(SettingDefinition(
        "order_type",
        "订单类型",
        "order",
        "select",
        "market",
        ScopePolicy.GROUP_OVERRIDE,
        module="order_execution",
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
        module="order_matching",
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
        module="order_sizing",
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
        module="liquidity",
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
        module="liquidity",
        minimum=0.0,
        maximum=1.0,
        step=0.01,
        chip_template="参与率: {value}",
        visible_when={"liquidity_mode": ("volume_participation",)},
    ))
    app.register_setting(SettingDefinition(
        "margin_mode", "保证金约束", "margin", "select", "market",
        ScopePolicy.GROUP_OVERRIDE,
        module="margin",
        options=(SettingOption("none", "关闭"), SettingOption("market", "市场保证金规则")),
        chip_template="保证金: {value}",
    ))
    app.register_setting(SettingDefinition(
        "collateral_fraction", "最大保证金占权益", "margin", "number", 1.0,
        ScopePolicy.GROUP_OVERRIDE, module="margin", minimum=0.01, maximum=1.0, step=0.01,
        chip_template="保证金上限: {value}",
        visible_when={"margin_mode": ("market",)},
    ))
    app.register_setting(SettingDefinition(
        "market_rule_fallback",
        "历史规则缺失处理",
        "market_rules",
        "select",
        "latest_available",
        ScopePolicy.LOCAL_ONLY,
        module="market_rules",
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
        module="accounting",
        options=(
            SettingOption("minor_units", "内部按分制整数记账"),
            SettingOption("engine_native", "使用执行引擎原生金额精度"),
        ),
        engine_defaults={"rqalpha": "engine_native"},
        disabled_values_by_engine={
            "rqalpha": ("minor_units",),
        },
        chip_template="金额精度: {value}",
    ))
    app.register_setting(SettingDefinition(
        "position_lot_policy",
        "持仓批次",
        "accounting",
        "select",
        "fifo",
        ScopePolicy.LOCAL_ONLY,
        module="accounting",
        options=(
            SettingOption("fifo", "FIFO 先进先出"),
        ),
        chip_template="持仓批次: {value}",
        help_text="用于期货平仓、平今/平昨费用与实现盈亏归属的批次语义；当前通用期货账本按 FIFO 管理 lot。",
    ))
    app.register_setting(SettingDefinition(
        "evaluation_split",
        "样本内截止日期",
        "evaluation",
        "date",
        None,
        ScopePolicy.LOCAL_ONLY,
        module="evaluation_range",
        chip_template="样本内截止: {value}",
        help_text="截止日期之后为样本外；留空表示全部为样本内。",
    ))
    app.register_setting(SettingDefinition(
        "calendar_frequency", "公共回测时钟", "calendar", "select", "auto",
        ScopePolicy.LOCAL_ONLY,
        module="backtest_calendar",
        options=(
            SettingOption("auto", "按因子频率自动判断"),
            SettingOption("1min", "1 分钟"),
            SettingOption("5min", "5 分钟"),
            SettingOption("1day", "1 天"),
        ),
        chip_template="时钟: {value}",
    ))
    # 分组测试：本地设置面板 + 分组列表（多选、一次运行所有选中、点击行编辑）。
    app.register_surface(SettingsSurface(
        "local", "本地设置", TabMountPoint.LOCAL_SETTINGS, kind="panel", order=10,
    ))
    app.register_surface(SettingsSurface(
        "groups", "分组", TabMountPoint.GROUP_SETTINGS, kind="list", order=20,
        selection="multi", run_mode="run_all", editable=True, item_label="分组",
    ))
    # 分组列表支持的 flow（声明元数据；行为仍由前端 GT.modes 提供）。
    for flow in (
        SurfaceFlow("groups", "add_group", "新增分组", "create", order=0, form_tab="add-group"),
        SurfaceFlow("groups", "create_derived", "派生组", "derive", order=10,
                    form_tab="add-derived", min_selected=1, max_selected=1),
        SurfaceFlow("groups", "create_ls", "创建 Long-Short 组合", "compose", order=20,
                    min_selected=2, max_selected=2),
        SurfaceFlow("groups", "clone", "复制为派生组", "clone", order=30,
                    form_tab="add-derived", min_selected=1, max_selected=1),
        SurfaceFlow("groups", "edit", "编辑", "edit", order=40, min_selected=1, max_selected=1),
        SurfaceFlow("groups", "delete", "删除", "delete", order=50, min_selected=1,
                    button_class="btn-outline-danger"),
    ):
        app.register_flow(flow)
    return app


def ic_test_settings() -> ApplicationSettings:
    app = ApplicationSettings("ic_test")
    app.register_accepted_global_default_keys(*RUN_WINDOW_KEYS, *PRODUCT_PATH_CANDIDATE_KEYS, *PRODUCT_PATH_SELECTION_KEYS, *FACTOR_CANDIDATE_KEYS, *FACTOR_SELECTION_KEYS, *MARKET_DATA_SELECTION_KEYS)
    for module in (
        SettingModule("factor_execution", "因子执行", "factor", 10),
        SettingModule("product_selection", "品种/路径选择", "product", 20),
        SettingModule("run_window", "运行时间范围", "backtest", 30),
        SettingModule("market_data_source", "数据源", "market_data", 35),
        SettingModule("market_data_frequency", "数据频率", "market_data", 36),
        SettingModule("return_frequency", "收益率频率", "analysis", 40),
        SettingModule("return_definition", "收益率定义", "analysis", 50),
        SettingModule("ic_delay", "IC Delay", "analysis", 60),
        SettingModule("ic_method", "IC 类型", "analysis", 70),
        SettingModule("cross_section", "截面处理", "analysis", 80),
        SettingModule("ic_summary", "IC 汇总", "analysis", 90),
    ):
        app.register_module(module)
    for tab in (
        SettingTab("factor", "因子执行", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 10),
        SettingTab(
            "product_path_selection",
            "产品路径",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            20,
        ),
        SettingTab(
            "time",
            "时间范围",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            30,
            summary_template="{start_date} → {end_date} · {time_precision}",
            summary_keys=("start_date", "end_date", "time_precision"),
        ),
        SettingTab("data_source", "数据源", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 35),
        SettingTab("frequency", "数据频率", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 36),
        SettingTab("return_frequency", "收益率频率", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 40),
        SettingTab("delay", "Delay", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 50),
        SettingTab("ic_method", "IC 类型", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 55),
        SettingTab("cross_section", "截面处理", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 58),
        SettingTab("summary", "汇总", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 60),
    ):
        app.register_tab(tab)
    for chip in (
        ChipDefinition(
            "factor_alias",
            "因子",
            "identity",
            "因子: {factorAlias}",
            ("factorAlias",),
            module="factor_execution",
            order=10,
            inherit_from_root=True,
        ),
        ChipDefinition(
            "product_path_selection",
            "产品路径",
            "identity",
            "产品路径: {productPathSelectionLabel}",
            ("product_path_selection",),
            module="product_selection",
            order=20,
            value_resolvers={"productPathSelectionLabel": "product_path_selection_label"},
            clickable=True,
        ),
    ):
        app.register_chip_field(chip)
    register_factor_execution_base(app)
    # IC 只用复数多选字段：为每个 product_path 跑所有 factor_selections。
    # 候选列表是多选的回退来源（本地→全局），不注册单数 factor / product_path_selection。
    register_factor_candidate_list_base(app)
    register_factor_selections_base(app)
    register_product_path_candidate_list_base(app)
    register_product_path_selections_base(app)
    register_market_data_base(app, include_price_type=False)
    register_run_window_base(app)
    app.register_setting(SettingDefinition(
        "return_frequency_mode",
        "收益率频率",
        "return_frequency",
        "select",
        "factor_frequency",
        ScopePolicy.LOCAL_ONLY,
        module="return_frequency",
        options=(
            SettingOption("factor_frequency", "跟随因子频率"),
            SettingOption("daily", "日频"),
            SettingOption("minute", "分钟频"),
        ),
        chip_template="收益频率: {value}",
    ))
    app.register_setting(SettingDefinition(
        "return_price_basis",
        "收益口径",
        "return_frequency",
        "select",
        "next_open_to_open_adjusted",
        ScopePolicy.LOCAL_ONLY,
        module="return_definition",
        options=(
            SettingOption("next_open_to_open_adjusted", "下一期开盘到开盘（复权）"),
            SettingOption("next_close_to_close_adjusted", "下一期收盘到收盘（复权）"),
        ),
        chip_template="收益口径: {value}",
    ))
    app.register_setting(SettingDefinition(
        "ic_lag",
        "IC Lag",
        "delay",
        "number",
        0,
        ScopePolicy.LOCAL_ONLY,
        module="ic_delay",
        minimum=0,
        step=1,
        chip_template="Lag: {value}",
    ))
    app.register_setting(SettingDefinition(
        "ic_correlation",
        "默认 IC",
        "ic_method",
        "select",
        "rank",
        ScopePolicy.LOCAL_ONLY,
        module="ic_method",
        options=(
            SettingOption("rank", "Cross-sectional Rank IC"),
            SettingOption("pearson", "Cross-sectional Pearson IC"),
            SettingOption("both", "Rank IC + Pearson IC"),
        ),
        chip_template="IC: {value}",
    ))
    app.register_setting(SettingDefinition(
        "group_adjust",
        "组内去均值",
        "cross_section",
        "select",
        "off",
        ScopePolicy.LOCAL_ONLY,
        module="cross_section",
        options=(
            SettingOption("off", "关闭"),
            SettingOption("on", "按组调整收益"),
        ),
        chip_template="组调整: {value}",
    ))
    app.register_setting(SettingDefinition(
        "by_group",
        "分组 IC",
        "cross_section",
        "select",
        "off",
        ScopePolicy.LOCAL_ONLY,
        module="cross_section",
        options=(
            SettingOption("off", "关闭"),
            SettingOption("on", "按组输出"),
        ),
        chip_template="分组IC: {value}",
    ))
    app.register_setting(SettingDefinition(
        "min_cross_section_count",
        "最小截面样本数",
        "cross_section",
        "number",
        5,
        ScopePolicy.LOCAL_ONLY,
        module="cross_section",
        minimum=2,
        step=1,
        chip_template="最小样本: {value}",
    ))
    app.register_setting(SettingDefinition(
        "ic_decay_lags",
        "IC 衰减阶数",
        "delay",
        "number",
        5,
        ScopePolicy.LOCAL_ONLY,
        module="ic_delay",
        minimum=1,
        step=1,
        chip_template="衰减阶数: {value}",
    ))
    app.register_setting(SettingDefinition(
        "rolling_window",
        "滚动窗口",
        "summary",
        "number",
        20,
        ScopePolicy.LOCAL_ONLY,
        module="ic_summary",
        minimum=2,
        step=1,
        chip_template="滚动窗口: {value}",
    ))
    for tab in (
        ResultTabDefinition(
            "cross_sectional_rank_ic",
            "Cross-sectional Rank IC",
            "ic_method",
            10,
            default=True,
            requires={"ic_correlation": ("rank", "both")},
        ),
        ResultTabDefinition(
            "cross_sectional_pearson_ic",
            "Cross-sectional Pearson IC",
            "ic_method",
            20,
            requires={"ic_correlation": ("pearson", "both")},
        ),
        ResultTabDefinition("ic_summary", "IC Summary", "ic_summary", 30),
        ResultTabDefinition("ic_decay", "IC Decay", "ic_delay", 40),
        ResultTabDefinition("rolling_ic", "Rolling IC", "ic_summary", 50),
        ResultTabDefinition(
            "by_group_ic",
            "By Group IC",
            "cross_section",
            60,
            requires={"by_group": ("on",)},
        ),
        ResultTabDefinition("coverage_missing", "Coverage / Missing", "cross_section", 70),
    ):
        app.register_result_tab(tab)
    # IC：本地设置面板 + IC 配置列表（单选、选中后运行、点击行编辑）。
    app.register_surface(SettingsSurface(
        "local", "IC 本地设置", TabMountPoint.LOCAL_SETTINGS, kind="panel", order=10,
    ))
    app.register_surface(SettingsSurface(
        "ic_configs", "IC 配置", TabMountPoint.GROUP_SETTINGS, kind="list", order=20,
        selection="single", run_mode="select_then_run", editable=True, item_label="IC 配置",
    ))
    for flow in (
        SurfaceFlow("ic_configs", "add_config", "新增 IC 配置", "create", order=0),
        SurfaceFlow("ic_configs", "edit", "编辑", "edit", order=10, min_selected=1, max_selected=1),
        SurfaceFlow("ic_configs", "delete", "删除", "delete", order=20, min_selected=1,
                    button_class="btn-outline-danger"),
    ):
        app.register_flow(flow)
    return app


def factor_evaluation_settings() -> ApplicationSettings:
    app = ApplicationSettings("factor_evaluation")
    app.register_accepted_global_default_keys(*RUN_WINDOW_KEYS, *PRODUCT_PATH_CANDIDATE_KEYS, *PRODUCT_PATH_SELECTION_KEYS, *FACTOR_CANDIDATE_KEYS, *FACTOR_SELECTION_KEYS, *MARKET_DATA_SELECTION_KEYS)
    for module in (
        SettingModule("product_selection", "产品选择", "product", 10),
        SettingModule("run_window", "计算时间范围", "time", 20),
        SettingModule("market_data_source", "数据源", "market_data", 30),
        SettingModule("market_data_frequency", "价格频率", "market_data", 40),
        SettingModule("price_transform", "价格处理", "market_data", 50),
        SettingModule("factor_execution", "因子选择", "factor", 60),
    ):
        app.register_module(module)
    for tab in (
        SettingTab(
            "product",
            "产品",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            10,
            (TabMountPoint.LOCAL_SETTINGS,),
        ),
        SettingTab(
            "time",
            "时间范围",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            20,
            summary_template="{start_date} → {end_date} · {time_precision}",
            summary_keys=("start_date", "end_date", "time_precision"),
        ),
        SettingTab("data_source", "数据源", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 30),
        SettingTab("frequency", "频率", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 40),
        SettingTab("price_type", "价格类型", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 50),
        SettingTab(
            "factor",
            "因子",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            60,
            (TabMountPoint.LOCAL_SETTINGS,),
        ),
    ):
        app.register_tab(tab)
    register_run_window_base(app)
    app.register_setting(SettingDefinition(
        "product",
        "产品路径",
        "product",
        "select",
        None,
        ScopePolicy.LOCAL_ONLY,
        module="product_selection",
        chip_template="产品路径: {value}",
        help_text="从后端注册的产品树选择一个产品或产品路径。",
    ))
    register_product_path_candidate_list_base(app, tab="product")
    register_market_data_base(app, include_price_type=True)
    register_factor_candidate_list_base(app)
    register_factor_selection_base(app)
    return app


def factor_type_analysis_settings() -> ApplicationSettings:
    """因子类型分析的 settings 注册（用于产品序列下方的平行模块）。"""
    app = ApplicationSettings("factor_type_analysis")
    app.register_accepted_global_default_keys(*RUN_WINDOW_KEYS, *PRODUCT_PATH_CANDIDATE_KEYS, *PRODUCT_PATH_SELECTION_KEYS, *FACTOR_CANDIDATE_KEYS, *FACTOR_SELECTION_KEYS, *MARKET_DATA_SELECTION_KEYS)
    for module in (
        SettingModule("product_selection", "产品选择", "product", 10),
        SettingModule("run_window", "计算时间范围", "time", 20),
        SettingModule("market_data_source", "数据源", "market_data", 25),
        SettingModule("market_data_frequency", "数据频率", "market_data", 26),
        SettingModule("factor_execution", "因子选择", "factor", 30),
        SettingModule("analysis_method", "分析方法", "method", 40),
    ):
        app.register_module(module)
    for tab in (
        SettingTab(
            "product_path_selection",
            "产品路径",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            10,
            (TabMountPoint.LOCAL_SETTINGS,),
        ),
        SettingTab(
            "time",
            "时间范围",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            20,
            summary_template="{start_date} → {end_date} · {time_precision}",
            summary_keys=("start_date", "end_date", "time_precision"),
        ),
        SettingTab("data_source", "数据源", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 25),
        SettingTab("frequency", "数据频率", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 26),
        SettingTab(
            "factor",
            "因子",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            30,
            (TabMountPoint.LOCAL_SETTINGS,),
        ),
        SettingTab(
            "method",
            "分析方法",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            40,
            (TabMountPoint.LOCAL_SETTINGS,),
        ),
    ):
        app.register_tab(tab)
    register_run_window_base(app)
    register_product_path_candidate_list_base(app)
    register_product_path_selection_base(app)
    register_market_data_base(app, include_price_type=False)
    register_factor_candidate_list_base(app)
    register_factor_selection_base(app)
    app.register_setting(SettingDefinition(
        "correlation_method",
        "相关性方法",
        "method",
        "select",
        "pearson",
        ScopePolicy.LOCAL_ONLY,
        module="analysis_method",
        options=(
            SettingOption("pearson", "Pearson（线性相关）"),
            SettingOption("spearman", "Spearman（秩相关）"),
        ),
        chip_template="方法: {value}",
    ))
    app.register_setting(SettingDefinition(
        "min_periods",
        "最少有效期数",
        "method",
        "number",
        30,
        ScopePolicy.LOCAL_ONLY,
        module="analysis_method",
        minimum=2,
        step=1,
        chip_template="最少期数: {value}",
        help_text="相关性计算所需的最少重叠时间点；低于该数量时标记为数据不足。",
    ))
    app.register_result_tab(ResultTabDefinition(
        "type_overview",
        "类型概览",
        "analysis_method",
        10,
        default=True,
        help_text="展示最接近的因子类型及按类别聚合的相关性。",
    ))
    app.register_result_tab(ResultTabDefinition(
        "reference_factors",
        "参照因子",
        "analysis_method",
        20,
        help_text="展示待测因子与各参照因子的相关性。",
    ))
    app.register_result_tab(ResultTabDefinition(
        "product_profiles",
        "产品画像",
        "product_selection",
        30,
        help_text="展示每个产品更接近哪些因子类型，以及每个类型下最相关的产品。",
    ))
    return app


backtest_setting_registry = BacktestSettingRegistry()
backtest_setting_registry.register(single_factor_page_settings())
backtest_setting_registry.register(group_test_settings())
backtest_setting_registry.register(ic_test_settings())
backtest_setting_registry.register(factor_evaluation_settings())
backtest_setting_registry.register(factor_type_analysis_settings())

"""IC-test application settings."""

from __future__ import annotations

from typing import Any

from tools.testers._shared import (
    CATEGORY_CANDIDATE_KEYS,
    CATEGORY_SELECTION_KEYS,
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTIONS_KEYS,
    FACTOR_SOURCE_KEYS,
    MARKET_DATA_SELECTION_KEYS,
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTIONS_KEYS,
    RUN_WINDOW_KEYS,
    register_category_candidate_list_base,
    register_category_selection_base,
    register_factor_candidate_list_base,
    register_factor_execution_base,
    register_factor_selections_base,
    register_factor_source_base,
    register_market_data_base,
    register_product_path_candidate_list_base,
    register_product_path_selections_base,
    register_run_window_base,
    register_test_template_base,
)
from tools.testers.settings.contracts import (
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
from tools.testers.settings.registry import ApplicationSettings


def register_ic_test_settings(app: ApplicationSettings) -> None:
    """Register all IC-test infrastructure settings on an ApplicationSettings."""
    app.register_accepted_global_default_keys(
        *RUN_WINDOW_KEYS,
        *PRODUCT_PATH_CANDIDATE_KEYS,
        *PRODUCT_PATH_SELECTIONS_KEYS,
        *FACTOR_CANDIDATE_KEYS,
        *FACTOR_SELECTIONS_KEYS,
        *FACTOR_SOURCE_KEYS,
        *CATEGORY_CANDIDATE_KEYS,
        *CATEGORY_SELECTION_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
    )
    for module in (
        SettingModule("factor_execution", "因子执行", "factor", 10),
        SettingModule("product_selection", "品种/路径选择", "product", 20),
        SettingModule("category_grouping", "分类分组", "product", 25),
        SettingModule("run_window", "运行时间范围", "backtest", 30),
        SettingModule("market_data_source", "数据源", "market_data", 35),
        SettingModule("market_data_frequency", "数据频率", "market_data", 36),
        SettingModule("return_frequency", "前瞻收益", "analysis", 40),
        SettingModule("return_definition", "收益率定义", "analysis", 50),
        SettingModule("ic_delay", "IC Delay", "analysis", 60),
        SettingModule("ic_method", "IC 类型", "analysis", 70),
        SettingModule("cross_section", "截面处理", "analysis", 80),
        SettingModule("ic_summary", "IC 汇总", "analysis", 90),
        SettingModule("quantile_portfolio_statistics", "分组组合统计", "analysis", 95),
    ):
        app.register_module(module)
    register_test_template_base(app)
    for tab in (
        SettingTab(
            "factor", "因子执行", (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid", 10, (TabMountPoint.LOCAL_SETTINGS,),
            content_adapter="factor_selection",
        ),
        SettingTab(
            "category", "分类", (TabMountPoint.LOCAL_SETTINGS,),
            "custom", 15, content_adapter="category_selection",
        ),
        SettingTab(
            "product_path_selection",
            "产品路径",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            20,
            (TabMountPoint.LOCAL_SETTINGS,),
            content_adapter="product_path_selection",
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
        SettingTab("return_frequency", "前瞻收益", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 40),
        SettingTab("delay", "Delay", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 50),
        SettingTab("ic_method", "IC 类型", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 55),
        SettingTab("cross_section", "截面处理", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 58),
        SettingTab("summary", "汇总", (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 60),
        SettingTab(
            "quantile_portfolio_statistics", "分组组合", (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid", 65,
        ),
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
            target_tab="factor",
            order=10,
            inherit_from_root=True,
            batch_owned=True,
            source_adapter="selected_factors",
        ),
        ChipDefinition(
            "product_path_selection",
            "产品路径",
            "identity",
            "产品路径: {productPathSelectionLabel}",
            ("product_path_selection",),
            module="product_selection",
            target_tab="product_path_selection",
            order=20,
            value_resolvers={"productPathSelectionLabel": "product_path_selection_label"},
            clickable=True,
            source_adapter="selected_product_paths",
        ),
    ):
        app.register_chip_field(chip)
    register_factor_execution_base(app)
    # IC 只用复数多选字段：为每个 product_path 跑所有 factor_selections。
    # 候选列表是多选的回退来源（本地→全局），不注册单数 factor / product_path_selection。
    register_factor_source_base(app)
    register_factor_candidate_list_base(app)
    register_factor_selections_base(app)
    register_product_path_candidate_list_base(app)
    register_product_path_selections_base(app)
    # 分类：by_group IC 的分组维度（候选 + 选中），管理方式同 product_path/factor。
    register_category_candidate_list_base(app)
    register_category_selection_base(app)
    register_market_data_base(app, include_price_type=False)
    register_run_window_base(app)
    app.register_setting(SettingDefinition(
        "forward_return_horizons",
        "前瞻收益期",
        "return_frequency",
        "ic_horizon_grid",
        {"sampling": "scale_aware"},
        ScopePolicy.LOCAL_ONLY,
        module="return_frequency",
        help_text="可按因子频率自动生成，或冻结多个基准与倍数；首个结果作为默认展示收益期",
        chip_template="收益期: {value}",
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
        "ic_lags",
        "入场延迟",
        "delay",
        "ic_delay_grid",
        [0],
        ScopePolicy.LOCAL_ONLY,
        module="ic_delay",
        help_text="以信号 bar 为单位分别计算多个延迟；0 表示信号可成交时立即进入，首项用于默认展示",
        chip_template="延迟: {value}",
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
        "IC 重采样间隔",
        "delay",
        "ic_decay_grid",
        [5],
        ScopePolicy.LOCAL_ONLY,
        module="ic_delay",
        help_text=(
            "按每 N 个 IC 观测抽取一个样本，分别报告重采样后的均值、波动、IR 与 t 统计；"
            "不是入场延迟或自相关阶数"
        ),
        chip_template="重采样间隔: {value}",
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
    app.register_setting(SettingDefinition(
        "quantile_portfolio_statistics",
        "分组组合统计",
        "quantile_portfolio_statistics",
        "custom",
        {
            "enabled": True,
            "group_count": 5,
            "modes": ["no_fee", "fee_margin_target"],
            "target_margin_utilization": 0.30,
            "initial_capital": 1.0,
            "include_return_series": False,
        },
        ScopePolicy.LOCAL_ONLY,
        module="quantile_portfolio_statistics",
        help_text=(
            "把 IC 结果转换为向量化分组组合统计；包含无费率和按品种比例费率/固定保证金利用率模式。"
            " Avg Turnover 是目标名义权重变化代理，不含真实成交、整手和流动性。"
        ),
        chip_template="分组组合: {value}",
        serialization={
            "kind": "quantile_portfolio_statistics",
            "display_order": 10,
            "modes": ["no_fee", "fee_margin_target"],
            "turnover_semantics": "target_weight_proxy",
        },
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
            "quantile_portfolio_statistics",
            "Quantile Portfolio Statistics",
            "quantile_portfolio_statistics",
            55,
        ),
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

"""IC tabs, chips, shared inputs, and module ownership."""

from __future__ import annotations

from tools.testers._shared import (
    CATEGORY_CANDIDATE_KEYS,
    CATEGORY_SELECTION_KEYS,
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTIONS_KEYS,
    FACTOR_SET_SELECTION_KEYS,
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
    register_factor_set_selections_base,
    register_factor_source_base,
    register_market_data_base,
    register_product_path_candidate_list_base,
    register_product_path_selections_base,
    register_run_window_base,
    register_test_template_base,
)
from tools.testers.run_input_contracts import factor_source_content_options
from tools.testers.settings.contracts import (
    ChipDefinition,
    SettingModule,
    SettingTab,
    TabMountPoint,
)
from tools.testers.settings.registry import ApplicationSettings


def register_authoring_shell(app: ApplicationSettings) -> None:
    _register_global_keys(app)
    _register_modules(app)
    register_test_template_base(app)
    _register_tabs(app)
    _register_chips(app)
    _register_shared_inputs(app)


def _register_global_keys(app: ApplicationSettings) -> None:
    app.register_accepted_global_default_keys(
        *RUN_WINDOW_KEYS,
        *PRODUCT_PATH_CANDIDATE_KEYS,
        *PRODUCT_PATH_SELECTIONS_KEYS,
        *FACTOR_CANDIDATE_KEYS,
        *FACTOR_SET_SELECTION_KEYS,
        *FACTOR_SELECTIONS_KEYS,
        *FACTOR_SOURCE_KEYS,
        *CATEGORY_CANDIDATE_KEYS,
        *CATEGORY_SELECTION_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
    )


def _register_modules(app: ApplicationSettings) -> None:
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
        SettingModule(
            "quantile_portfolio_statistics", "分组组合统计", "analysis", 95,
        ),
    ):
        app.register_module(module)


def _register_tabs(app: ApplicationSettings) -> None:
    local = (TabMountPoint.LOCAL_SETTINGS,)
    for tab in (
        SettingTab(
            "factor", "因子执行", local, "settings-grid", 10, local,
            content_adapter="factor_selection",
            content_options=factor_source_content_options(),
        ),
        SettingTab(
            "category", "分类", local, "custom", 15,
            content_adapter="category_selection",
        ),
        SettingTab(
            "product_path_selection", "产品路径", local, "settings-grid", 20,
            local, content_adapter="product_path_selection",
        ),
        SettingTab(
            "time", "时间范围", local, "settings-grid", 30,
            summary_template="{start_date} → {end_date} · {time_precision}",
            summary_keys=("start_date", "end_date", "time_precision"),
        ),
        SettingTab("data_source", "数据源", local, "settings-grid", 35),
        SettingTab("frequency", "数据频率", local, "settings-grid", 36),
        SettingTab("return_frequency", "前瞻收益", local, "settings-grid", 40),
        SettingTab("delay", "Delay", local, "settings-grid", 50),
        SettingTab("ic_method", "IC 类型", local, "settings-grid", 55),
        SettingTab("cross_section", "截面处理", local, "settings-grid", 58),
        SettingTab("summary", "汇总", local, "settings-grid", 60),
        SettingTab(
            "quantile_portfolio_statistics", "分组组合", local,
            "settings-grid", 65,
        ),
    ):
        app.register_tab(tab)


def _register_chips(app: ApplicationSettings) -> None:
    app.register_chip_field(ChipDefinition(
        "factor_alias", "因子", "identity", "因子: {factorAlias}",
        ("factorAlias",), module="factor_execution", target_tab="factor",
        order=10, inherit_from_root=True, batch_owned=True,
        source_adapter="selected_factors",
    ))
    app.register_chip_field(ChipDefinition(
        "product_path_selection", "产品路径", "identity",
        "产品路径: {productPathSelectionLabel}",
        ("product_path_selection",), module="product_selection",
        target_tab="product_path_selection", order=20,
        value_resolvers={
            "productPathSelectionLabel": "product_path_selection_label",
        },
        clickable=True, source_adapter="selected_product_paths",
    ))


def _register_shared_inputs(app: ApplicationSettings) -> None:
    register_factor_execution_base(app)
    register_factor_source_base(app)
    register_factor_candidate_list_base(app)
    register_factor_set_selections_base(app)
    register_factor_selections_base(app)
    register_product_path_candidate_list_base(app)
    register_product_path_selections_base(app)
    register_category_candidate_list_base(app)
    register_category_selection_base(app)
    register_market_data_base(app, include_price_type=False)
    register_run_window_base(app)

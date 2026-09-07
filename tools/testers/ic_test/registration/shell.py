"""IC tabs, chips, shared inputs, and module ownership."""

from __future__ import annotations

from tools.testers._shared import (
    CATEGORY_CANDIDATE_KEYS,
    CATEGORY_SELECTION_KEYS,
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTIONS_KEYS,
    FACTOR_SET_SELECTION_KEYS,
    FACTOR_SOURCE_SELECTION_KEYS,
    MARKET_DATA_SELECTION_KEYS,
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTIONS_KEYS,
    RUN_WINDOW_KEYS,
    register_category_candidate_list_base,
    register_category_selection_base,
    register_factor_candidate_list_base,
    register_factor_execution_base,
    register_factor_product_scope_chips,
    register_factor_selections_base,
    register_factor_set_selections_base,
    register_factor_source_selections_base,
    register_market_data_base,
    register_product_path_candidate_list_base,
    register_product_path_selections_base,
    register_run_window_base,
    register_test_template_base,
)
from tools.testers.settings.contracts import (
    ChipDefinition,
    ScopePolicy,
    SettingModule,
    SettingsSection,
    SettingTab,
    TabMountPoint,
)
from tools.testers.settings.registry import ApplicationSettings


def register_authoring_shell(app: ApplicationSettings) -> None:
    _register_global_keys(app)
    _register_modules(app)
    register_test_template_base(app)
    _register_sections(app)
    _register_tabs(app)
    _register_chips(app)
    _register_shared_inputs(app)


def _register_global_keys(app: ApplicationSettings) -> None:
    app.register_accepted_global_default_keys(
        *RUN_WINDOW_KEYS,
        *PRODUCT_PATH_CANDIDATE_KEYS,
        *PRODUCT_PATH_SELECTIONS_KEYS,
        *FACTOR_CANDIDATE_KEYS,
        *FACTOR_SELECTIONS_KEYS,
        *FACTOR_SET_SELECTION_KEYS,
        *FACTOR_SOURCE_SELECTION_KEYS,
        *CATEGORY_CANDIDATE_KEYS,
        *CATEGORY_SELECTION_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
    )


def _register_modules(app: ApplicationSettings) -> None:
    for module in (
        SettingModule("ic_configuration_group", "配置", "analysis", 5),
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
        SettingModule("ic_summary", "IC 汇总", "analysis", 90),
        SettingModule(
            "quantile_portfolio_statistics", "分组组合统计", "analysis", 95,
        ),
    ):
        app.register_module(module)


def _register_sections(app: ApplicationSettings) -> None:
    """Declare the authoring sequence without teaching the client IC fields."""
    for section in (
        SettingsSection(
            "authoring", "配置与模板",
            "先加载模板，再确认本次测试的研究对象与输出方式", 10,
        ),
        SettingsSection(
            "scope", "研究对象",
            "先选定因子、产品路径与分类；这些选择定义本次 IC 核心矩阵", 20,
        ),
        SettingsSection(
            "data", "样本与数据",
            "固定样本窗口、数据源和频率，避免把预热数据误当统计样本", 30,
        ),
        SettingsSection(
            "core", "IC 核心矩阵",
            "由前瞻收益期、入场延迟和 IC 类型组成，可一次选择多组核心组合", 40,
        ),
        SettingsSection(
            "analysis", "附加分析",
            "核心结果完成后再添加重采样、滚动和分组组合统计，不改变核心测试身份", 50,
        ),
    ):
        app.register_settings_section(section)
    for section, tabs in {
        "authoring": ("test_template",),
        "scope": ("factor", "category", "product_path_selection"),
        "data": ("time", "data_source", "frequency"),
        "core": ("return_frequency", "delay", "ic_method"),
        "analysis": ("summary", "quantile_portfolio_statistics"),
    }.items():
        for tab in tabs:
            app.set_tab_section(tab, section)


def _register_tabs(app: ApplicationSettings) -> None:
    local = (TabMountPoint.LOCAL_SETTINGS,)
    group = (TabMountPoint.GROUP_SETTINGS,)
    for tab in (
        SettingTab(
            "factor", "因子执行", local, "settings-grid", 10, local,
            content_adapter="factor_selection",
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
        SettingTab("summary", "汇总", local, "settings-grid", 60),
        SettingTab(
            "quantile_portfolio_statistics", "分组组合", local,
            "settings-grid", 65,
        ),
    ):
        app.register_tab(tab)
    # These fields define one IC configuration group. They remain registered
    # for schema/default/chip reuse, but must never appear in the outer test
    # settings shell.
    for tab in (
        SettingTab("return_frequency", "前瞻收益", group, "settings-grid", 40),
        SettingTab("delay", "Delay", group, "settings-grid", 50),
        SettingTab("ic_method", "IC 类型", group, "settings-grid", 55),
    ):
        app.register_tab(tab)


def _register_chips(app: ApplicationSettings) -> None:
    register_factor_product_scope_chips(app)
    app.register_chip_field(ChipDefinition(
        "configuration_name", "配置", "identity",
        "配置: {configurationName}", ("configurationName",),
        module="ic_configuration_group", target_tab="__configuration__",
        order=5, source_adapter="primary_ic_configuration_group",
        display_scope="strategy",
    ))
    app.register_chip_field(ChipDefinition(
        "category", "分类", "identity",
        "分类: {categoryLabel}", ("categoryLabel",),
        module="category_grouping", target_tab="category", order=15,
        source_adapter="selected_category", clickable=True,
        detail_overlay={
            "kind": "category", "mode": "view", "source_key": "category",
        },
    ))


def _register_shared_inputs(app: ApplicationSettings) -> None:
    register_factor_execution_base(app, scope_policy=ScopePolicy.OVERRIDABLE)
    register_factor_candidate_list_base(app)
    register_factor_selections_base(app)
    register_factor_set_selections_base(app)
    register_factor_source_selections_base(app)
    register_product_path_candidate_list_base(app)
    register_product_path_selections_base(app)
    register_category_candidate_list_base(app)
    register_category_selection_base(app)
    register_market_data_base(
        app, include_price_type=False, automatic_only=True,
    )
    register_run_window_base(app)

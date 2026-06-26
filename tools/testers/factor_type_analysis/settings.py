"""Factor-type-analysis application settings."""

from __future__ import annotations

from typing import Any

from tools.testers.settings.applications import (
    FACTOR_CANDIDATE_KEYS,
    FACTOR_SELECTION_KEYS,
    MARKET_DATA_SELECTION_KEYS,
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTION_KEYS,
    RUN_WINDOW_KEYS,
    register_factor_candidate_list_base,
    register_factor_selection_base,
    register_market_data_base,
    register_product_path_candidate_list_base,
    register_product_path_selection_base,
    register_run_window_base,
)
from tools.testers.settings.contracts import (
    ResultTabDefinition,
    ScopePolicy,
    SettingDefinition,
    SettingModule,
    SettingOption,
    SettingTab,
    TabMountPoint,
)
from tools.testers.settings.registry import ApplicationSettings


def register_factor_type_analysis_settings(app: ApplicationSettings) -> None:
    """Register all factor-type-analysis infrastructure settings on an ApplicationSettings."""
    app.register_accepted_global_default_keys(
        *RUN_WINDOW_KEYS,
        *PRODUCT_PATH_CANDIDATE_KEYS,
        *PRODUCT_PATH_SELECTION_KEYS,
        *FACTOR_CANDIDATE_KEYS,
        *FACTOR_SELECTION_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
    )
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

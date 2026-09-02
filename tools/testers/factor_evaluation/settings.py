"""Factor-evaluation application settings."""

from __future__ import annotations

from tools.testers._shared import (
    CATEGORY_CANDIDATE_KEYS,
    CATEGORY_SELECTION_KEYS,
    FACTOR_CANDIDATE_KEYS,
    FACTOR_EXECUTION_KEYS,
    FACTOR_SET_SELECTION_KEYS,
    FACTOR_SELECTION_KEYS,
    FACTOR_SOURCE_SELECTION_KEYS,
    MARKET_DATA_SELECTION_KEYS,
    PRODUCT_PATH_CANDIDATE_KEYS,
    PRODUCT_PATH_SELECTION_KEYS,
    RUN_WINDOW_KEYS,
    register_factor_candidate_list_base,
    register_factor_execution_base,
    register_factor_set_selections_base,
    register_factor_selection_base,
    register_factor_source_selections_base,
    register_market_data_base,
    register_category_candidate_list_base,
    register_category_selection_base,
    register_product_path_candidate_list_base,
    register_product_path_selection_base,
    register_run_window_base,
)
from tools.testers.settings.contracts import (
    SettingModule,
    SettingTab,
    TabMountPoint,
)
from tools.testers.settings.registry import ApplicationSettings


def register_factor_evaluation_settings(app: ApplicationSettings) -> None:
    """Register all factor-evaluation infrastructure settings on an ApplicationSettings."""
    app.register_accepted_global_default_keys(
        *RUN_WINDOW_KEYS,
        *PRODUCT_PATH_CANDIDATE_KEYS,
        *PRODUCT_PATH_SELECTION_KEYS,
        *CATEGORY_CANDIDATE_KEYS,
        *CATEGORY_SELECTION_KEYS,
        *FACTOR_CANDIDATE_KEYS,
        *FACTOR_EXECUTION_KEYS,
        *FACTOR_SET_SELECTION_KEYS,
        *FACTOR_SELECTION_KEYS,
        *FACTOR_SOURCE_SELECTION_KEYS,
        *MARKET_DATA_SELECTION_KEYS,
    )
    for module in (
        SettingModule("product_selection", "产品选择", "product", 10),
        SettingModule("category_grouping", "产品分类", "category", 15),
        SettingModule("run_window", "计算时间范围", "time", 20),
        SettingModule("market_data_source", "数据源", "market_data", 30),
        SettingModule("market_data_frequency", "价格频率", "market_data", 40),
        SettingModule("price_transform", "价格处理", "market_data", 50),
        SettingModule("factor_execution", "因子选择", "factor", 60),
    ):
        app.register_module(module)
    for tab in (
        SettingTab(
            "product_path_selection",
            "产品组",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            10,
            (TabMountPoint.LOCAL_SETTINGS,),
            content_adapter="product_path_selection",
        ),
        SettingTab(
            "category",
            "产品分类",
            (TabMountPoint.LOCAL_SETTINGS,),
            "settings-grid",
            15,
            content_adapter="category_selection",
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
            content_adapter="factor_selection",
        ),
    ):
        app.register_tab(tab)
    register_run_window_base(app)
    register_product_path_candidate_list_base(app, tab="product_path_selection")
    register_product_path_selection_base(app, tab="product_path_selection")
    register_category_candidate_list_base(app, tab="category")
    register_category_selection_base(app, tab="category")
    register_market_data_base(app, include_price_type=True)
    register_factor_candidate_list_base(app)
    register_factor_execution_base(app, warmup_mode_default="none")
    register_factor_set_selections_base(app)
    register_factor_source_selections_base(app)
    register_factor_selection_base(app)

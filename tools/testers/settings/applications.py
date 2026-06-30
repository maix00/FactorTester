"""Built-in tester application setting registrations."""

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
from tools.products.product_path_selection import ProductPathSelection

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
CATEGORY_SELECTION_KEYS = ("category",)
CATEGORY_CANDIDATE_KEYS = ("category_candidates",)
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
    app.register_setting(SettingDefinition(
        "warmup_mode",
        "前摇窗口",
        tab,
        "select",
        "auto",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
        options=(
            SettingOption("none", "不使用"),
            SettingOption("fixed", "固定时间"),
            SettingOption("auto", "按因子表达式自动推导"),
        ),
        chip_template="前摇窗口: {value}",
        default_when={"engine_mode": {"basic": "none", "auto": "auto", "custom": "auto", "exact": "auto"}},
        help_text="只用于扩大因子计算窗口和 live bar 预热事件；正式信号窗口、绩效统计窗口不随之改变。",
    ))
    app.register_setting(SettingDefinition(
        "warmup_window",
        "前摇时长",
        tab,
        "text",
        "30d",
        ScopePolicy.LOCAL_ONLY,
        module="factor_execution",
        chip_template="前摇时长: {value}",
        visible_when={"warmup_mode": ("fixed",)},
        help_text="固定前摇窗口必须是时间值，例如 30min、5d、60d。",
    ))


def register_run_window_base(
    app: ApplicationSettings,
    *,
    tab: str = "time",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    tab_kwargs = {
        "tab_label": "时间范围",
        "tab_order": 40,
        "tab_summary_template": "{start_date} → {end_date} · {time_precision}",
        "tab_summary_keys": ("start_date", "end_date", "time_precision"),
    }
    app.register_setting(SettingDefinition(
        "start_date", "开始日期", tab, "date", "", scope_policy,
        module="run_window", chip_template="开始日期: {value}",
        serialization={"display_order": 10},
        **tab_kwargs,
    ))
    app.register_setting(SettingDefinition(
        "end_date", "结束日期", tab, "date", "", scope_policy,
        module="run_window", chip_template="结束日期: {value}",
        serialization={"display_order": 20},
        **tab_kwargs,
    ))
    app.register_setting(SettingDefinition(
        "start_time", "开始时间", tab, "time", "00:00", scope_policy,
        module="run_window", chip_template="开始时间: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 40},
        **tab_kwargs,
    ))
    app.register_setting(SettingDefinition(
        "end_time", "结束时间", tab, "time", "23:59", scope_policy,
        module="run_window", chip_template="结束时间: {value}",
        visible_when={"time_precision": ("exact",)},
        serialization={"display_order": 50},
        **tab_kwargs,
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
        **tab_kwargs,
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
        **tab_kwargs,
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
        info_overlay={"type": "product_path_selection_products"},
        instance_class=ProductPathSelection,
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
        tab_label="产品路径",
        tab_order=30,
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
        info_overlay={"type": "product_path_selection_products"},
        instance_class=ProductPathSelection,
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
        tab_label="产品路径",
        tab_order=30,
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
            "factor_library_source": "user_factor_library_overview",
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
        tab_label="因子执行",
        tab_order=20,
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
        info_overlay={"type": "factor_info"},
        serialization={
            "kind": "factor_selection",
            "display_order": 20,
            "candidate_field": "factor_candidates",
            # 模块内单选为空时回退到页面共享的 factor。
            "shared_page_field": "factor",
            "id_keys": ("alias", "name", "factor_alias"),
            "label_keys": ("alias", "name", "label"),
        },
        tab_label="因子执行",
        tab_order=20,
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
        info_overlay={"type": "factor_info"},
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


# ── 分类(Category)：与 factor / product_path 同构的三元组，驱动 by_group IC ──────
# 一个 Category = 一组互不相交的路径组(类别)，组外产品归入"其他"。候选可来自
# 数据源已定义的 Category（如 LocalCNFutures 的 行业/日夜盘/行业×日夜盘，来源"数据库"）、
# 用户自定义("自定义")、或现场新增("现场")。
def register_category_candidate_list_base(
    app: ApplicationSettings,
    *,
    tab: str = "category",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "category_candidates",
        "分类候选列表",
        tab,
        "custom",
        [],
        scope_policy,
        module="category_grouping",
        chip_template="分类候选: {value}",
        help_text="分类候选：数据源内置(数据库) + 用户自定义 + 现场新增；每个分类是一组不相交的路径组。",
        serialization={
            "kind": "category_candidate_list",
            "display_order": 10,
            "item_kind": "category",
            "shared_page_field": "category_candidates",
            "selection_field": "category",
            "category_source": "data_source_categories",
            "fallback_policy": (
                "copy_page_candidates",
                "load_data_source_categories_when_page_empty",
            ),
            "id_keys": ("name", "id"),
            "label_keys": ("name", "label"),
            "mutation_scope": {
                "page": "page_candidates_only",
                "module": "module_candidates_only",
            },
        },
    ))


def register_category_selection_base(
    app: ApplicationSettings,
    *,
    tab: str = "category",
    scope_policy: ScopePolicy = ScopePolicy.LOCAL_ONLY,
) -> None:
    app.register_setting(SettingDefinition(
        "category",
        "分类",
        tab,
        "select",
        "",
        scope_policy,
        module="category_grouping",
        chip_template="分类: {value}",
        serialization={
            "kind": "category_selection",
            "display_order": 20,
            "candidate_field": "category_candidates",
            "shared_page_field": "category",
            "id_keys": ("name", "id"),
            "label_keys": ("name", "label"),
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
        serialization={"kind": "setting_template"},
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

    # Infrastructure settings (SettingModules, SettingTabs, ChipDefinitions,
    # and non-module SettingDefinitions) — moved to tools/testers/backtest/settings.py.
    from tools.testers.backtest.settings import register_group_test_settings
    register_group_test_settings(app)

    # Module-owned settings (fee, slippage, liquidity, margin) — from
    # each ExecutableModule's setting_definitions classvar.
    from tools.testers.backtest.modules.registry import register_all_module_settings
    register_all_module_settings(app)

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
    from tools.testers.ic_test.settings import register_ic_test_settings
    register_ic_test_settings(app)

    return app


def factor_evaluation_settings() -> ApplicationSettings:
    app = ApplicationSettings("factor_evaluation")
    from tools.testers.factor_evaluation.settings import register_factor_evaluation_settings
    register_factor_evaluation_settings(app)

    return app


def factor_type_analysis_settings() -> ApplicationSettings:
    """因子类型分析的 settings 注册（用于产品序列下方的平行模块）。"""
    app = ApplicationSettings("factor_type_analysis")
    from tools.testers.factor_type_analysis.settings import register_factor_type_analysis_settings
    register_factor_type_analysis_settings(app)

    return app


backtest_setting_registry = BacktestSettingRegistry()
backtest_setting_registry.register(single_factor_page_settings())
backtest_setting_registry.register(group_test_settings())
backtest_setting_registry.register(ic_test_settings())
backtest_setting_registry.register(factor_evaluation_settings())
backtest_setting_registry.register(factor_type_analysis_settings())

"""Built-in tester application setting registrations."""

from __future__ import annotations

from .contracts import (
    ChipDefinition,
    ResultTabDefinition,
    RunFieldDefinition,
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
from tools.testers.field_spec import ValueDescriptor

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


def register_run_fields(
    app: ApplicationSettings, *, backtest: bool, output_picker: bool = True,
) -> None:
    """Register per-run controls separately from reusable configuration fields."""
    app.register_manifest_extension(
        "run_settings",
        {
            "key": "run_context",
            "label": "任务提交",
            "description": "本次任务的名称、提交身份、结果保留和生成物选择",
            "order": 0,
            "default_mounted": True,
        },
    )
    app.register_run_field(RunFieldDefinition(
        "task_name", "任务名称", "text", "", "body",
        "job.task_name", "run_identity", order=1,
        help_text="可留空；留空时任务列表使用运行配置标识",
    ))
    app.register_run_field(RunFieldDefinition(
        "acting_profile_ref", "提交身份", "profile", "", "body",
        "job.acting_profile_ref", "run_identity", order=2,
        help_text="选择本次任务使用的 Profile；留空时使用当前用户",
    ))
    app.register_run_field(RunFieldDefinition(
        "service_port", "服务端口", "service_port", "", "query",
        "job.server_context.port", "global_settings", order=10,
        help_text="可填写固定端口；留空时由 Manager 自动选择可用服务端口",
    ))
    # These controls are intentionally Swift-only.  The Swift client may
    # choose to execute inside its isolated local runtime; the ordinary web
    # submission surface must remain a server-run form and never receive
    # local code/package references.
    app.register_run_field(RunFieldDefinition(
        "execution_target", "运行位置", "select", "server", "body",
        "run_spec.execution_target", "run_options", order=15,
        options=(
            SettingOption("server", "服务器运行"),
            SettingOption("local", "Swift 客户端本地运行"),
        ),
        client_targets=("swift",),
        value_descriptor=ValueDescriptor(
            "enum", editor="select", option_source="manifest.options",
        ),
        help_text=(
            "仅 Swift 客户端可选；本地运行不会把任务提交到 Manager，"
            "而是在客户端隔离运行时内执行。"
        ),
    ))
    app.register_run_field(RunFieldDefinition(
        "local_runtime_server_ref", "本地运行服务器", "text", "", "body",
        "run_spec.local_runtime.server_ref", "run_options", order=16,
        client_targets=("swift",),
        visible_if={"execution_target": ("local",)},
        value_descriptor=ValueDescriptor(
            "reference", editor="server_picker", ref_kind="manager_server",
            option_source="server.federation",
        ),
        help_text="选择提供研究图与运行代码的 Manager；代码按需从该服务器 7997 获取。",
    ))
    app.register_run_field(RunFieldDefinition(
        "local_runtime_bundle_ref", "本地运行代码包", "text", "", "body",
        "run_spec.local_runtime.bundle_ref", "run_options", order=17,
        client_targets=("swift",),
        visible_if={"execution_target": ("local",)},
        value_descriptor=ValueDescriptor(
            "source_file", editor="runtime_bundle_picker",
            ref_kind="factor_test_runtime", option_source="server.7997",
        ),
        help_text="选择按需下载的 FactorTester 运行代码包；不会随 Swift 应用预置。",
    ))
    app.register_run_field(RunFieldDefinition(
        "retention_mode", "结果保留范围", "select", "summary", "body",
        "run_spec.retention_mode", "run_options", order=20,
        options=(
            SettingOption("summary", "摘要结果"),
            SettingOption("full", "完整运行结果"),
        ),
        help_text="摘要模式按已选生成物保留必要结果；完整模式保留可供后续诊断的运行明细",
    ))
    if backtest:
        app.register_run_field(RunFieldDefinition(
            "step_mode", "逐步运行", "boolean", False, "body",
            "run_spec.step_mode", "run_options", order=30,
            help_text="逐个 flow 暂停并输出审计字段；仅支持单个回测分析",
        ))
    if output_picker:
        app.register_run_field(RunFieldDefinition(
            "output_requests", "结果与生成物", "artifact_output_picker", [], "body",
            "run_spec.output_requests", "outputs", template_policy="include", order=40,
            help_text="提交前选择的输出会冻结进 RunSpec，也可在任务完成后继续生成",
        ))
    if not backtest:
        return
    app.register_run_field(RunFieldDefinition(
        "performance_profile", "累计性能剖析", "boolean", False, "body",
        "job.job_spec.performance_profile", "advanced_run_options", order=50,
        help_text="按 flow 累计耗时并在运行结束时输出热点；默认关闭",
        enabled_payload={"kind": "cumulative_flow", "min_total_ms": 1000.0},
    ))
    app.register_run_field(RunFieldDefinition(
        "margin_execution_profile", "保证金执行剖析", "boolean", False, "body",
        "job.job_spec.margin_execution_profile", "advanced_run_options", order=60,
        help_text="累计保证金预算检查、订单与组合投影耗时；默认关闭",
        enabled_payload={"kind": "cumulative", "min_total_ms": 0.0},
    ))


def register_factor_execution_base(app: ApplicationSettings, *, tab: str = "factor") -> None:
    warmup_default_if = (
        {
            "engine_mode": {
                "basic": "none",
                "auto": "auto",
                "custom": "auto",
                "exact": "auto",
            },
        }
        if "engine_mode" in app.settings
        else {}
    )
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
        default_if=warmup_default_if,
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
        visible_if={"warmup_mode": ("fixed",)},
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
        visible_if={"time_precision": ("exact",)},
        serialization={"display_order": 40},
        **tab_kwargs,
    ))
    app.register_setting(SettingDefinition(
        "end_time", "结束时间", tab, "time", "23:59", scope_policy,
        module="run_window", chip_template="结束时间: {value}",
        visible_if={"time_precision": ("exact",)},
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
        visible_if={"time_precision": ("exact",)},
        serialization={"display_order": 60},
        **tab_kwargs,
    ))
    app.register_setting(SettingDefinition(
        "evaluation_split", "样本切分", tab, "date", None, scope_policy,
        module="run_window", chip_template="样本切分: {value}",
        serialization={"display_order": 70},
        **tab_kwargs,
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
        execution_policy="authoring_only",
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
        help_text="选择数据源提供的分类用于 IC 分组；分类由数据源或用户产品分类提供。",
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


def group_test_settings() -> ApplicationSettings:
    app = ApplicationSettings("group_test")

    # Infrastructure settings (SettingModules, SettingTabs, ChipDefinitions,
    # and non-module SettingDefinitions) — moved to tools/testers/backtest/settings.py.
    from tools.testers.backtest.settings import register_group_test_settings
    register_group_test_settings(app)
    from tools.testers.settings.strategy_editor import register_strategy_editor_contract
    register_strategy_editor_contract(app)

    # Module-owned settings (fee, slippage, liquidity, margin) — from
    # each ExecutableModule's setting_definitions classvar.
    from tools.testers.backtest.modules.registry import register_all_module_settings
    register_all_module_settings(app)
    register_run_fields(app, backtest=True)
    # 任务提交由独立 run tab 固定显示；回测外层设置只预挂载其余三个
    # 核心 tab，因子、产品路径和运行输入均由用户按需挂载。
    app.set_default_mounted_tabs(
        TabMountPoint.LOCAL_SETTINGS,
        ("test_template", "engine", "time"),
    )

    # 分组测试：本地设置面板 + 分组列表（多选、一次运行所有选中、点击行编辑）。
    app.register_surface(SettingsSurface(
        "local", "本地设置", TabMountPoint.LOCAL_SETTINGS, kind="panel", order=10,
    ))
    app.register_surface(SettingsSurface(
        "groups", "分组策略", TabMountPoint.GROUP_SETTINGS, kind="list", order=20,
        selection="multi", run_mode="run_all", editable=True, item_label="分组",
        content_adapter="backtest_groups",
    ))
    app.register_surface(SettingsSurface(
        "long_short", "分组多空策略", TabMountPoint.GROUP_SETTINGS, kind="list", order=30,
        selection="single", run_mode="run_all", editable=True,
        item_label="Long-Short 组合", content_adapter="backtest_long_short",
    ))
    from tools.testers.run_input_contracts import CUSTOM_STRATEGY_INPUTS
    app.register_surface(SettingsSurface(
        "custom_strategy", "自定义策略", TabMountPoint.GROUP_SETTINGS,
        kind="list", order=40, selection="single", run_mode="run_all",
        editable=True, item_label="自定义策略",
        content_adapter="backtest_custom_strategies",
        content_options={"inputs": CUSTOM_STRATEGY_INPUTS},
    ))
    # 分组列表支持的 flow（声明元数据；行为仍由前端 GT.modes 提供）。
    for flow in (
        SurfaceFlow("groups", "add_group", "新增分组", "create", order=0, form_tab="add-group"),
        SurfaceFlow("groups", "create_derived", "派生组", "derive", order=10,
                    form_tab="add-derived", min_selected=1, max_selected=1),
        SurfaceFlow("groups", "create_ls", "创建 Long-Short 组合", "compose", order=20,
                    min_selected=2, max_selected=2),
        SurfaceFlow("groups", "edit", "编辑", "edit", order=30, min_selected=1, max_selected=1),
        SurfaceFlow("groups", "rename", "重命名", "rename", order=35, min_selected=1, max_selected=1),
        SurfaceFlow("groups", "delete", "删除", "delete", order=40, min_selected=1,
                    button_class="btn-outline-danger"),
        SurfaceFlow("long_short", "rename_long_short", "重命名", "rename", order=5,
                    min_selected=1, max_selected=1),
        SurfaceFlow("long_short", "add_long_short", "新增 Long-Short 组合", "create", order=1),
        SurfaceFlow("long_short", "edit_long_short", "编辑", "edit", order=4,
                    min_selected=1, max_selected=1),
        SurfaceFlow("long_short", "swap_long_short", "交换多空", "swap", order=6,
                    min_selected=1, max_selected=1),
        SurfaceFlow("long_short", "delete_long_short", "删除", "delete", order=0,
                    min_selected=1, button_class="btn-outline-danger"),
    ):
        app.register_flow(flow)
    return app


def ic_test_settings() -> ApplicationSettings:
    app = ApplicationSettings("ic_test")
    from tools.testers.ic_test.settings import register_ic_test_settings
    register_ic_test_settings(app)
    from tools.testers.settings.strategy_editor import register_strategy_editor_contract
    register_strategy_editor_contract(app)
    register_run_fields(app, backtest=False)
    # Match the backtest configuration page: scope tabs are mounted only
    # after the user explicitly enables them from the left-side settings
    # manager.  The IC group editor owns its own factor/product pickers.
    app.set_default_mounted_tabs(
        TabMountPoint.LOCAL_SETTINGS,
        ("test_template", "time"),
    )

    return app


def factor_evaluation_settings() -> ApplicationSettings:
    app = ApplicationSettings("factor_evaluation")
    from tools.testers.factor_evaluation.settings import register_factor_evaluation_settings
    register_factor_evaluation_settings(app)
    register_run_fields(app, backtest=False)
    app.set_default_mounted_tabs(
        TabMountPoint.LOCAL_SETTINGS,
        ("product_path_selection", "time", "factor"),
    )

    return app


def factor_type_analysis_settings() -> ApplicationSettings:
    """因子类型分析的 settings 注册（用于产品序列下方的平行模块）。"""
    app = ApplicationSettings("factor_type_analysis")
    from tools.testers.factor_type_analysis.settings import register_factor_type_analysis_settings
    register_factor_type_analysis_settings(app)
    register_run_fields(app, backtest=False, output_picker=False)
    app.set_default_mounted_tabs(
        TabMountPoint.LOCAL_SETTINGS,
        ("product_path_selection", "time", "factor", "method"),
    )

    return app


backtest_setting_registry = BacktestSettingRegistry()
backtest_setting_registry.register(group_test_settings())
backtest_setting_registry.register(ic_test_settings())
backtest_setting_registry.register(factor_evaluation_settings())
backtest_setting_registry.register(factor_type_analysis_settings())

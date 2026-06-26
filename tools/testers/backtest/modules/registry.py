"""ModuleRegistry — unified entry point for executable modules, setting schemas,
and strategy parsing.

Inheritance chain:
    tools.data.modules.registry.ModuleRegistry  ← domain-neutral base
        BacktestModuleRegistry                   ← adds ApplicationSettings, full frontend manifest
            GroupTestModuleRegistry              ← group-test modules + group strategy parsing
            LongShortModuleRegistry              ← long-short modules + LS strategy parsing

Every module self-registers (no hardcoding in orchestrators or server endpoints).
The frontend receives the manifest from the registry — it knows nothing about
individual module files.
"""

from __future__ import annotations

from typing import Any

from tools.data.modules.registry import ModuleRegistry

from .base import ExecutableModule
from .fee import FeeModule
from .slippage import SlippageModule
from .liquidity import LiquidityModule
from .margin import MarginModule
from .position_sizing import PositionSizingModule
from .cash_rescale import CashRescaleModule


# ── All known ExecutableModule subclasses for backtest ───────────

_ALL_MODULE_CLASSES: tuple[type[ExecutableModule], ...] = (
    FeeModule,
    SlippageModule,
    LiquidityModule,
    MarginModule,
    PositionSizingModule,
    CashRescaleModule,
)


def _module_class_by_key() -> dict[str, type[ExecutableModule]]:
    result: dict[str, type[ExecutableModule]] = {}
    for cls in _ALL_MODULE_CLASSES:
        if not cls.key:
            raise ValueError(f"{cls.__name__} must define a non-empty `key`")
        if cls.key in result:
            raise ValueError(f"duplicate module key: {cls.key}")
        result[cls.key] = cls
    return result


# ── Settings registration (standalone — import-safe) ──────────────

def register_all_module_settings(app: Any) -> None:
    """Register SettingDefinitions from all executable modules into an ApplicationSettings.

    Iterates _ALL_MODULE_CLASSES, reads each class's setting_definitions
    classvar (dict format), and calls app.register_setting().

    This is a module-level function (not a method) so applications.py can
    import it without triggering a circular import through BacktestModuleRegistry.
    """
    from tools.testers.settings.contracts import ScopePolicy, SettingDefinition, SettingOption

    _SCOPE_MAP = {p.value: p for p in ScopePolicy}
    for cls in sorted(_ALL_MODULE_CLASSES, key=lambda c: getattr(c, "order", 0)):
        for sd in getattr(cls, "setting_definitions", ()):
            sd = dict(sd)
            scope_raw = sd.pop("scope_policy", "group_override")
            scope = _SCOPE_MAP.get(scope_raw, ScopePolicy.GROUP_OVERRIDE)
            options_raw = sd.pop("options", ())
            options = tuple(
                SettingOption(str(o[0]), str(o[1])) if isinstance(o, (tuple, list)) else o
                for o in options_raw
            )
            app.register_setting(SettingDefinition(
                module=cls.key,
                scope_policy=scope,
                options=options,
                **sd,
            ))


# ── BacktestModuleRegistry ────────────────────────────────────────

# Import at runtime to avoid circular imports
def _get_backtest_setting_registry():
    from tools.testers.settings import backtest_setting_registry
    return backtest_setting_registry


class BacktestModuleRegistry(ModuleRegistry):
    """Adds ApplicationSettings and produces a combined frontend manifest.

    The manifest merges:
      - Settings schema from ApplicationSettings (tabs, settings, chips, etc.)
      - Executable module info from ModuleRegistry (base)

    Strategy parsing is deferred to subclasses (GroupTest / LongShort).
    """

    _module_classes = _ALL_MODULE_CLASSES

    def __init__(self) -> None:
        super().__init__()
        self._registry = _get_backtest_setting_registry()

    def get_app(self) -> Any:
        """Return the ApplicationSettings for self.application."""
        return self._registry.get(self.application)

    # ── full manifest (frontend-facing) ─────────────────────────

    def manifest(self) -> dict[str, Any]:
        """Combined manifest: settings + executable modules."""
        app = self.get_app()
        settings_manifest = app.manifest()
        settings_manifest["executable_modules"] = self.module_manifest()
        settings_manifest["strategy_kind"] = self.application
        return settings_manifest

    def tab_manifest(self, tab_key: str) -> dict[str, Any]:
        """Per-tab view of the manifest."""
        app = self.get_app()
        tab_manifest = app.tab_manifest(tab_key)
        tab_manifest["executable_modules"] = self.module_manifest()
        return tab_manifest

    # ── helper: get all setting keys for a module ───────────────

    def setting_keys_for_module(self, module_key: str) -> list[str]:
        """Return all setting keys owned by a given module."""
        app = self.get_app()
        return [
            key for key, s in app.settings.items()
            if s.module == module_key
        ]

    def setting_values_for_strategy(
        self,
        strategy: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Extract per-module settings from a strategy dict.

        Returns {module_key: {setting_key: value, ...}, ...}
        """
        app = self.get_app()
        result: dict[str, dict[str, Any]] = {}
        for key, setting in app.settings.items():
            if key in strategy:
                result.setdefault(setting.module, {})[key] = strategy[key]
        return result

    def collect_local_only_settings(
        self,
        resolved_by_group: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Extract LOCAL_ONLY settings from resolved per-group settings.

        LOCAL_ONLY settings are identical across all groups; we read them
        from the first group. Returns {module_key: {setting_key: value, ...}}.
        Delegating reads to this method removes hardcoded key names from
        callers like _run_group_test_core.

        Example:
            common = registry.collect_local_only_settings(resolved)
            engine = common.get("execution_engine", {}).get("engine", "native")
        """
        from ..settings.contracts import ScopePolicy
        if not resolved_by_group:
            return {}
        app = self.get_app()
        # Use the first group's resolved settings as the source
        first_settings = next(iter(resolved_by_group.values()))
        result: dict[str, dict[str, Any]] = {}
        for key, setting in app.settings.items():
            if setting.scope_policy == ScopePolicy.LOCAL_ONLY and key in first_settings:
                result.setdefault(setting.module, {})[key] = first_settings[key]
        return result

    # ── _FactorGroupTestGroup construction ─────────────────────

    def build_group_params(
        self,
        group_settings: dict[str, Any],
        raw_group: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect _FactorGroupTestGroup construction params from all modules.

        First calls the base (executable modules), then adds settings-derived
        params that every group needs but no executable module explicitly owns
        (rebalance_trigger, position_policy, etc.), plus raw_group-derived
        identity fields (product_list, name, _id, etc.).

        Returns merged dict of all _FactorGroupTestGroup constructor params
        except the pure loop-context fields (tester_id, factor_alias,
        n_groups, group_index).
        """
        # 1) Executable module params (fee, liquidity, margin...)
        merged = super().build_group_params(group_settings, raw_group)

        # 2) Settings-derived params — any group_settings key that maps to
        #    a known setting gets forwarded if not already contributed.
        app = self.get_app()
        for key, setting in app.settings.items():
            if key in group_settings and key not in merged:
                merged[key] = group_settings[key]

        # 3) Identity fields from raw_group (frontend payload)
        merged["_id"] = str(raw_group.get("id") or "")
        if "name" not in merged:
            merged["name"] = _group_display_name(raw_group)
        if "key" not in merged:
            merged["key"] = merged["name"]
        if "product_list" not in merged:
            merged["product_list"] = _product_list_from_raw_group(raw_group)
        if "use_close_today" not in merged:
            merged["use_close_today"] = False

        return merged

    # ── strategy parsing (subclasses override) ──────────────────

    def parse_strategy(self, config: dict[str, Any]) -> dict[str, Any]:
        """Parse a strategy config dict into a normalized strategy dict.

        Subclasses override to add kind-specific parsing (group membership,
        long/short legs, etc.).
        """
        raise NotImplementedError("subclass must implement parse_strategy")


# ── GroupTestModuleRegistry ───────────────────────────────────────


class GroupTestModuleRegistry(BacktestModuleRegistry):
    """Registry for group-test (membership) strategies.

    Parses group configs with membership_index, group_id, display_name.
    Supports sourcing fee_rate from the legacy fee_mode/custom_fee_rate.
    """

    application = "group_test"

    # ── Settings registration ──────────────────────────────────

    @staticmethod
    def register_settings(app: Any) -> None:
        """Register all group_test infrastructure settings on an ApplicationSettings.

        Covers SettingModules, SettingTabs, ChipDefinitions, and non-module
        SettingDefinitions (engine, capital, allocation, rebalance, position,
        order execution, market rules, accounting, evaluation, calendar).

        Module-owned settings (fee, slippage, liquidity, margin) are registered
        separately by register_all_module_settings(app).
        """
        from tools.testers.settings.contracts import (
            ChipDefinition, ScopePolicy, SettingDefinition, SettingModule,
            SettingOption, SettingTab, TabMountPoint,
        )
        from tools.testers.settings.applications import (
            register_factor_execution_base,
            register_factor_candidate_list_base,
            register_factor_selection_base,
            register_product_path_candidate_list_base,
            register_product_path_selection_base,
            register_market_data_base,
            register_run_window_base,
            RUN_WINDOW_KEYS,
            PRODUCT_PATH_CANDIDATE_KEYS,
            PRODUCT_PATH_SELECTION_KEYS,
            FACTOR_CANDIDATE_KEYS,
            FACTOR_SELECTION_KEYS,
            MARKET_DATA_SELECTION_KEYS,
        )

        app.register_accepted_global_default_keys(
            *RUN_WINDOW_KEYS,
            *PRODUCT_PATH_CANDIDATE_KEYS,
            *PRODUCT_PATH_SELECTION_KEYS,
            *FACTOR_CANDIDATE_KEYS,
            *FACTOR_SELECTION_KEYS,
            *MARKET_DATA_SELECTION_KEYS,
        )

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
            SettingModule("order_matching", "撮合", "execution", 130),
            SettingModule("order_sizing", "数量取整", "execution", 140),
            SettingModule(
                "liquidity", "流动性", "execution", 150,
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

        # ── SettingTabs ─────────────────────────────────────────
        for tab in (
            SettingTab("engine", "执行引擎", (TabMountPoint.LOCAL_SETTINGS,),
                       "settings-grid", 10, (TabMountPoint.LOCAL_SETTINGS,)),
            SettingTab("factor", "因子执行",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 12),
            SettingTab("product_path_selection", "产品路径",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 13),
            SettingTab("group_strategy", "分组数量",
                       (TabMountPoint.GROUP_SETTINGS,), "settings-grid", 14),
            SettingTab("data_source", "数据源",
                       (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 15),
            SettingTab("frequency", "数据频率",
                       (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 16),
            SettingTab("time", "时间范围",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 17,
                       summary_template="{start_date} → {end_date} · {time_precision}",
                       summary_keys=("start_date", "end_date", "time_precision")),
            SettingTab("capital", "资金",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 20),
            SettingTab("target_allocation", "目标分配",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 25),
            SettingTab("rebalance_trigger", "调仓触发",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 30),
            SettingTab("position_policy", "持仓政策",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 32),
            SettingTab("cost", "费用",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 40),
            SettingTab("order", "订单执行",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 45),
            SettingTab("liquidity", "流动性",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 50),
            SettingTab("margin", "保证金",
                       (TabMountPoint.LOCAL_SETTINGS, TabMountPoint.GROUP_SETTINGS),
                       "settings-grid", 55),
            SettingTab("market_rules", "市场规则",
                       (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 60),
            SettingTab("accounting", "记账规则",
                       (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 62),
            SettingTab("calendar", "回测时钟",
                       (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 65),
            SettingTab("evaluation", "样本划分",
                       (TabMountPoint.LOCAL_SETTINGS,), "settings-grid", 70),
        ):
            app.register_tab(tab)

        # ── ChipDefinitions ─────────────────────────────────────
        for chip in (
            ChipDefinition("factor_alias", "因子", "identity",
                           "因子: {factorAlias}", ("factorAlias",),
                           module="factor_execution", order=10,
                           inherit_from_root=True, batch_owned=True),
            ChipDefinition("product_path_selection", "产品路径", "identity",
                           "产品路径: {productPathSelectionLabel}",
                           ("product_path_selection",),
                           module="product_selection", order=20,
                           inherit_from_root=True,
                           value_resolvers={"productPathSelectionLabel": "product_path_selection_label"},
                           clickable=True, batch_owned=True),
            ChipDefinition("split_count", "分组数", "identity",
                           "分组数: {splitCount}", ("splitCount",),
                           module="group_strategy", order=30,
                           inherit_from_root=True, batch_owned=True),
            ChipDefinition("group_index", "分组序号", "identity",
                           "分组序号: {groupIndex}", ("groupIndex",),
                           module="group_strategy", order=31,
                           inherit_from_root=True),
            ChipDefinition("product_mask", "品种范围", "derived",
                           "品种范围: {productCount}品种 {expandSymbol}",
                           ("productMask",),
                           module="product_selection", order=40,
                           value_resolvers={
                               "productCount": "product_mask_count",
                               "expandSymbol": "product_mask_expand_symbol",
                           },
                           clickable=True),
        ):
            app.register_chip_field(chip)

        # ── Infrastructure SettingDefinitions ──────────────────
        app.register_setting(SettingDefinition(
            "engine", "回测引擎", "engine", "select", "native",
            ScopePolicy.LOCAL_ONLY, module="execution_engine",
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
            "splitCount", "分组数", "group_strategy", "number", 5,
            ScopePolicy.GROUP_ONLY, module="group_strategy",
            minimum=1, step=1, chip_template="分组数: {value}",
        ))
        app.register_setting(SettingDefinition(
            "groupIndex", "分组序号", "group_strategy", "number", 1,
            ScopePolicy.GROUP_ONLY, module="group_strategy",
            minimum=1, step=1, chip_template="分组序号: {value}",
        ))
        app.register_setting(SettingDefinition(
            "initial_capital", "初始资金", "capital", "number", 100_000_000.0,
            ScopePolicy.GROUP_OVERRIDE, module="portfolio_capital",
            minimum=0.01, step=10_000.0, chip_template="资金: {value}",
        ))
        app.register_setting(SettingDefinition(
            "base_currency", "基础货币", "capital", "select", "CNY",
            ScopePolicy.GROUP_OVERRIDE, module="portfolio_capital",
            options=(SettingOption("CNY", "CNY"), SettingOption("USD", "USD")),
            chip_template="币种: {value}",
        ))
        app.register_setting(SettingDefinition(
            "currency_conversion_fee_rate", "换汇佣金率", "capital", "number", 0.0,
            ScopePolicy.GROUP_OVERRIDE, module="portfolio_capital",
            minimum=0.0, step=0.000001,
        ))
        app.register_setting(SettingDefinition(
            "allocation_policy", "目标分配", "target_allocation", "select",
            "inverse_volatility", ScopePolicy.GROUP_OVERRIDE,
            module="target_allocation",
            options=(
                SettingOption("inverse_volatility", "等风险（波动率倒数）"),
                SettingOption("equal_notional", "等市值"),
                SettingOption("equal_margin", "等保证金（对照）"),
            ),
            chip_template="分配: {value}",
        ))
        app.register_setting(SettingDefinition(
            "volatility_lookback", "波动率回看期数", "target_allocation",
            "number", 20, ScopePolicy.GROUP_OVERRIDE,
            module="target_allocation", minimum=2, step=1,
            chip_template="波动率窗口: {value}",
            visible_when={"allocation_policy": ("inverse_volatility",)},
        ))
        app.register_setting(SettingDefinition(
            "volatility_warmup", "等风险预热处理", "target_allocation", "select",
            "equal_notional", ScopePolicy.GROUP_OVERRIDE,
            module="target_allocation",
            options=(
                SettingOption("equal_notional", "预热期使用等市值并记录"),
                SettingOption("error", "数据不足即报错"),
            ),
            visible_when={"allocation_policy": ("inverse_volatility",)},
        ))
        app.register_setting(SettingDefinition(
            "rebalance_trigger", "触发规则", "rebalance_trigger", "select",
            "on_factor_signal", ScopePolicy.GROUP_OVERRIDE,
            module="rebalance_trigger",
            options=(
                SettingOption("on_factor_signal", "因子信号事件"),
                SettingOption("membership_change", "成员变化事件"),
                SettingOption("scheduled", "日历计划事件"),
            ),
            chip_template="触发: {value}",
        ))
        app.register_setting(SettingDefinition(
            "position_policy", "仓位处理", "position_policy", "select",
            "rebalance_to_target", ScopePolicy.GROUP_OVERRIDE,
            module="position_policy",
            options=(
                SettingOption("rebalance_to_target", "按目标调仓"),
                SettingOption("buy_and_hold", "买入持有"),
            ),
            chip_template="持仓: {value}",
        ))
        app.register_setting(SettingDefinition(
            "execution_timing", "执行时点", "order", "select", "next_bar",
            ScopePolicy.GROUP_OVERRIDE, module="order_execution",
            options=(
                SettingOption("next_bar", "下一 bar 执行"),
                SettingOption("same_bar", "本 bar 执行"),
            ),
            chip_template="执行: {value}",
        ))
        app.register_setting(SettingDefinition(
            "execution_price_basis", "执行价格", "order", "select", "open",
            ScopePolicy.GROUP_OVERRIDE, module="order_execution",
            options=(
                SettingOption("close", "收盘/切片价格"),
                SettingOption("open", "开盘价"),
                SettingOption("vwap", "VWAP"),
            ),
            chip_template="价格: {value}",
        ))
        app.register_setting(SettingDefinition(
            "execution_delay_bars", "执行延迟 bar 数", "order", "number", 1,
            ScopePolicy.GROUP_OVERRIDE, module="order_execution",
            minimum=1, step=1,
            chip_template="延迟: {value} 根 bar",
            help_text="仅在「下一 bar 执行」时生效；1 表示信号产生后的下一根 bar 执行。",
            visible_when={"execution_timing": ("next_bar",)},
        ))
        app.register_setting(SettingDefinition(
            "order_type", "订单类型", "order", "select", "market",
            ScopePolicy.GROUP_OVERRIDE, module="order_execution",
            options=(
                SettingOption("market", "市价单"),
                SettingOption("limit", "限价单"),
            ),
            chip_template="订单: {value}",
        ))
        app.register_setting(SettingDefinition(
            "matching_model", "撮合模型", "order", "select", "next_bar_full_fill",
            ScopePolicy.GROUP_OVERRIDE, module="order_matching",
            options=(
                SettingOption("next_bar_full_fill", "下一 bar 全额成交"),
                SettingOption("bar_volume_limited", "按 bar 成交量限制"),
            ),
            chip_template="撮合: {value}",
        ))
        app.register_setting(SettingDefinition(
            "quantity_rounding_policy", "数量取整", "order", "select",
            "floor_to_lot", ScopePolicy.GROUP_OVERRIDE, module="order_sizing",
            options=(
                SettingOption("floor_to_lot", "按最小买入手数向下取整"),
                SettingOption("nearest_lot", "按最小买入手数四舍五入"),
            ),
            chip_template="取整: {value}",
        ))
        app.register_setting(SettingDefinition(
            "market_rule_fallback", "历史规则缺失处理", "market_rules",
            "select", "latest_available", ScopePolicy.LOCAL_ONLY,
            module="market_rules",
            options=(
                SettingOption("latest_available", "使用最新规则并标记近似"),
                SettingOption("strict_historical", "缺失即报错"),
                SettingOption("configured_default", "使用注册默认值并标记近似"),
            ),
            chip_template="规则回退: {value}",
        ))
        app.register_setting(SettingDefinition(
            "money_unit_policy", "金额精度", "accounting", "select",
            "minor_units", ScopePolicy.LOCAL_ONLY, module="accounting",
            options=(
                SettingOption("minor_units", "内部按分制整数记账"),
                SettingOption("engine_native", "使用执行引擎原生金额精度"),
            ),
            engine_defaults={"rqalpha": "engine_native"},
            disabled_values_by_engine={"rqalpha": ("minor_units",)},
            chip_template="金额精度: {value}",
        ))
        app.register_setting(SettingDefinition(
            "position_lot_policy", "持仓批次", "accounting", "select",
            "fifo", ScopePolicy.LOCAL_ONLY, module="accounting",
            options=(SettingOption("fifo", "FIFO 先进先出"),),
            chip_template="持仓批次: {value}",
            help_text="用于期货平仓、平今/平昨费用与实现盈亏归属的批次语义；当前通用期货账本按 FIFO 管理 lot。",
        ))
        app.register_setting(SettingDefinition(
            "evaluation_split", "样本内截止日期", "evaluation", "date", None,
            ScopePolicy.LOCAL_ONLY, module="evaluation_range",
            chip_template="样本内截止: {value}",
            help_text="截止日期之后为样本外；留空表示全部为样本内。",
        ))
        app.register_setting(SettingDefinition(
            "calendar_frequency", "公共回测时钟", "calendar", "select", "auto",
            ScopePolicy.LOCAL_ONLY, module="backtest_calendar",
            options=(
                SettingOption("auto", "按因子频率自动判断"),
                SettingOption("1min", "1 分钟"),
                SettingOption("5min", "5 分钟"),
                SettingOption("1day", "1 天"),
            ),
            chip_template="时钟: {value}",
        ))

    # ── Strategy parsing ───────────────────────────────────────

    def parse_strategy(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize a group-test strategy config.

        Expected config keys:
          - membership_index: int
          - group_id: str
          - display_name: str (or group_name)
          - fee_rate: float (can come from fee_mode/custom_fee_rate)
          - initial_capital: float
          - ...other settings
        """
        parsed: dict[str, Any] = dict(config)
        parsed.setdefault("strategy_id", config.get("group_id", ""))
        parsed.setdefault("display_name", config.get("group_name") or config.get("group_id", ""))
        parsed.setdefault("strategy_kind", "group")
        if "fee_rate" not in parsed:
            parsed["fee_rate"] = _fee_rate_from_config(config)
        return parsed

    def parse_group_strategies(
        self,
        configs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parse a list of group strategy configs."""
        return [self.parse_strategy(c) for c in configs]

    # ── default module keys for group test ──────────────────────

    @property
    def default_module_keys(self) -> tuple[str, ...]:
        return (
            "transaction_cost",
            "slippage",
            "liquidity",
            "margin",
            "order_sizing",
            "cash_rescale",
        )

    # ── progress manifest (infrastructure + module phases) ─────

    _INFRA_PROGRESS_PHASES: tuple[dict[str, Any], ...] = (
        {"key": "init",                 "label": "初始化"},
        {"key": "factor_eval",          "label": "因子计算"},
        {"key": "signal_sequence",      "label": "因子信号序列"},
        {"key": "returns_eval",         "label": "收益率计算"},
        {"key": "membership",           "label": "分组隶属"},
        {"key": "flat_membership",      "label": "展开隶属"},
        {"key": "remap",                "label": "产品映射"},
        {"key": "trade_data",           "label": "交易数据", "sub_steps": {
            "start":          "开始加载",
            "load_returns":   "加载收益",
            "load_prices":    "加载价格",
            "merge_products": "合并品种",
            "settlement":     "处理结算",
            "spec_bundle":    "计算规格",
            "fill_returns":   "填充收益",
            "build_configs":  "构建配置",
            "ready":          "数据就绪",
        }},
        {"key": "simulate",             "label": "模拟中", "sub_steps": {
            "slicing":        "结果切片",
        }},
        {"key": "batch",                "label": "批次结果"},
        {"key": "serialize",            "label": "序列化"},
    )

    def build_progress_manifest(self) -> list[dict[str, Any]]:
        """Full progress manifest: infrastructure phases + module phases.

        Infrastructure phases come first (in declaration order), then
        module phases (deduplicated by key).
        """
        seen: dict[str, dict[str, Any]] = {}
        # Infrastructure phases first
        for phase in self._INFRA_PROGRESS_PHASES:
            key = str(phase["key"])
            entry = {"key": key, "label": str(phase["label"])}
            sub = phase.get("sub_steps")
            if sub:
                entry["sub_steps"] = dict(sub)
            seen[key] = entry
        # Module phases (dedup, merge sub_steps)
        for key, cls in sorted(self._by_key.items(), key=lambda kv: getattr(kv[1], "order", 0)):
            for phase in getattr(cls, "progress_phases", ()):
                phase_key = str(phase.get("key", ""))
                if not phase_key:
                    continue
                if phase_key in seen:
                    existing_sub = seen[phase_key].get("sub_steps") or {}
                    new_sub = phase.get("sub_steps") or {}
                    if new_sub:
                        seen[phase_key]["sub_steps"] = {**existing_sub, **new_sub}
                else:
                    seen[phase_key] = {
                        "key": phase_key,
                        "label": str(phase.get("label", phase_key)),
                    }
                    sub = phase.get("sub_steps")
                    if sub:
                        seen[phase_key]["sub_steps"] = dict(sub)
        return list(seen.values())


# ── LongShortModuleRegistry ───────────────────────────────────────


class LongShortModuleRegistry(BacktestModuleRegistry):
    """Registry for long-short strategies.

    Parses LS configs with long_indices, short_indices, and computes
    resolved settings from the source group(s).
    """

    application = "group_test"  # shares the same ApplicationSettings as group_test

    def parse_strategy(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize a long-short strategy config.

        Expected config keys:
          - long_indices: list[int] (group owner indices for long legs)
          - short_indices: list[int] (group owner indices for short legs)
          - strategy_id: str (e.g. "long-short:1")
          - display_name: str (or "name")
          - fee_rate: float
          - ...other settings (inherited from source group)
        """
        parsed: dict[str, Any] = dict(config)
        parsed.setdefault("strategy_id", config.get("name", ""))
        parsed.setdefault("display_name", config.get("name", ""))
        parsed.setdefault("strategy_kind", "long_short")
        if "fee_rate" not in parsed:
            parsed["fee_rate"] = _fee_rate_from_config(config)
        return parsed

    def parse_ls_strategies(
        self,
        configs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parse a list of long-short strategy configs."""
        return [self.parse_strategy(c) for c in configs]

    # ── default module keys for long-short ──────────────────────

    @property
    def default_module_keys(self) -> tuple[str, ...]:
        return (
            "transaction_cost",
            "slippage",
            "liquidity",
            "margin",
            "order_sizing",
            "cash_rescale",
        )


# ── Legacy fee-rate resolution (shared) ───────────────────────────


def _fee_rate_from_config(config: dict[str, Any]) -> float:
    """Resolve fee_rate from legacy fee_mode / custom_fee_rate."""
    mode = str(config.get("fee_mode", "market"))
    if mode == "none":
        return 0.0
    if mode == "custom":
        return float(config.get("custom_fee_rate", 0.0))
    # "market" mode — fee matrices forwarded per timestamp
    return 0.0


# ── Group identity helpers (shared) ────────────────────────────────

def _group_display_name(raw_group: dict[str, Any]) -> str:
    """Extract the display name from a frontend group payload."""
    return str(
        raw_group.get("shortAlias")
        or raw_group.get("name")
        or raw_group.get("key")
        or f'group-{raw_group.get("groupIndex", "?")}'
    )


def _product_list_from_raw_group(raw_group: dict[str, Any]) -> list[str] | None:
    """Extract product_list from a frontend group payload's productMask or productList."""
    raw = raw_group.get("productMask")
    if raw is None:
        raw = raw_group.get("productList")
    if isinstance(raw, dict):
        selected = [str(name) for name, enabled in raw.items() if enabled]
        return selected or None
    if isinstance(raw, list):
        selected = [str(name) for name in raw if name]
        return selected or None
    return None

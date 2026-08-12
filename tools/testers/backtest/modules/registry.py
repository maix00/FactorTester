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

from collections.abc import Iterable, Mapping
from typing import Any

from tools.data.modules.registry import ModuleRegistry

from .base import ExecutableModule
from .engine import EngineModule
from .strategy_book import StrategyBookModule
from .cash_pool import CashPoolModule
from .run_window import RunWindowModule
from .fee import FeeModule
from .slippage import SlippageModule
from .volume_capacity import VolumeCapacityMode
from .margin import MarginModule
from .margin_budget import MarginBudgetModule
from .order_execution import OrderExecutionModule
from .custom_product import CustomProductModule, refresh_custom_product_field_definitions
from .order_construct import OrderConstructModule
from .cash_rescale import LedgerCashConstraintModule
from .ledger_module import LedgerModule
from .trading_rule import TradingRuleModule
from .product_selection import ProductSelectionModule
from .term_structure import (
    DeliveryForceCloseModule,
    RolloverModule,
    TermStructureExpandModule,
)
from .market_data import MarketDataModule
from .bar_events import BarEventModule
from .minor_unit import MinorUnitModule
from .factor import FactorModule
from .factor_signal import FactorSignalModule
from .target import TargetStrategyModule
from .strategy_hooks import StrategyRuntime
from .group_membership import GroupMembershipModule
from .threshold_signal import ThresholdSignalModule
from .long_short import LongShortCompositionModule
from .term_carry import TermCarryStrategyModule
from .order_flow import OrderFlowModule
from .equity_curve import EquityCurveModule
from .risk_metrics import RiskMetricsModule


# ── All known ExecutableModule subclasses for backtest ───────────

_ALL_MODULE_CLASSES: tuple[type[ExecutableModule], ...] = (
    EngineModule,
    StrategyBookModule,
    CashPoolModule,
    RunWindowModule,
    LedgerModule,
    OrderConstructModule,
    TradingRuleModule,
    ProductSelectionModule,
    TermStructureExpandModule,
    DeliveryForceCloseModule,
    RolloverModule,
    MarketDataModule,
    BarEventModule,
    StrategyRuntime,
    MinorUnitModule,
    FactorModule,
    FactorSignalModule,
    TargetStrategyModule,
    GroupMembershipModule,
    ThresholdSignalModule,
    LongShortCompositionModule,
    TermCarryStrategyModule,
    FeeModule,
    SlippageModule,
    VolumeCapacityMode,
    MarginModule,
    MarginBudgetModule,
    OrderExecutionModule,
    CustomProductModule,
    LedgerCashConstraintModule,
    OrderFlowModule,
    EquityCurveModule,
    RiskMetricsModule,
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

def register_module_field_settings(
    app: Any,
    module_classes: Iterable[type[ExecutableModule]],
    *,
    setting_module_keys: Mapping[type[ExecutableModule], str] | None = None,
    tab_keys: Mapping[type[ExecutableModule], str] | None = None,
    scope_policy_overrides: Mapping[str, str] | None = None,
    add_missing_modules: bool = True,
) -> None:
    """Register an application's settings from executable module fields.

    `FieldDefinition` is the single field-schema source. Applications may
    retain their own high-level SettingModules/tabs, but must not duplicate a
    module field merely to change where it is mounted.
    """
    from tools.testers.settings.contracts import ScopePolicy, SettingDefinition, SettingModule, SettingOption, TabMountPoint
    setting_module_keys = setting_module_keys or {}
    tab_keys = tab_keys or {}
    scope_policy_overrides = scope_policy_overrides or {}
    _SCOPE_MAP = {p.value: p for p in ScopePolicy}
    for cls in sorted(module_classes, key=lambda c: getattr(c, "order", 0)):
        setting_module_key = setting_module_keys.get(cls, cls.key)
        if add_missing_modules and getattr(cls, "fields", None) and setting_module_key not in app.modules:
            app.register_module(SettingModule(
                key=setting_module_key, label=getattr(cls, "label", cls.key), layer="backtest",
                order=getattr(cls, "order", 100),
            ))
        for field_name, fd in getattr(cls, "fields", {}).items():
            if not fd.public:
                continue
            if field_name in app.settings:
                continue
            scope = _SCOPE_MAP.get(
                scope_policy_overrides.get(field_name, fd.scope_policy),
                ScopePolicy.OVERRIDABLE,
            )
            options = tuple(SettingOption(str(o[0]), str(o[1])) for o in fd.options)
            tab_defaults = tuple(
                TabMountPoint(value) for value in fd.tab_default_mount_points
            )
            app.register_setting(SettingDefinition(
                key=field_name,
                label=fd.label or field_name,
                tab=tab_keys.get(cls, fd.tab or cls.key),
                control_template=fd.control_template or "text",
                default=fd.default,
                module=setting_module_key,
                scope_policy=scope,
                options=options,
                minimum=fd.minimum,
                maximum=fd.maximum,
                step=fd.step,
                chip_template=fd.chip_template or None,
                info_overlay=fd.info_overlay,
                instance_class=fd.instance_class,
                help_text=fd.help_text,
                serialization=dict(fd.serialization or {}),
                visible_when=dict(fd.visible_when or {}),
                editable_when=dict(fd.editable_when or {}),
                default_when={
                    key: dict(values)
                    for key, values in (fd.default_when or {}).items()
                },
                tab_label=fd.tab_label,
                tab_order=fd.tab_order,
                tab_layout_template=fd.tab_layout_template,
                tab_default_mount_points=tab_defaults,
                tab_summary_template=fd.tab_summary_template,
                tab_summary_keys=fd.tab_summary_keys,
                tab_content_adapter=fd.tab_content_adapter,
                tab_content_options=dict(fd.tab_content_options or {}),
                adapter_managed=fd.adapter_managed,
                show_chip=fd.show_chip,
            ))


def register_all_module_settings(app: Any) -> None:
    """Register every executable module's public fields for group_test."""
    from tools.testers.settings.counterparty import apply_counterparty_profile_defaults

    refresh_custom_product_field_definitions()
    apply_counterparty_profile_defaults()
    register_module_field_settings(app, _ALL_MODULE_CLASSES)


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
        from tools.testers.settings.contracts import ScopePolicy
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

    # build_group_params (the _FactorGroupTestGroup-constructor-params
    # override that used to live here) was deleted along with
    # _FactorGroupTestGroup itself -- its only caller was the old
    # per-group core_params construction in
    # server/modules/single_factor_test/group.py, replaced by
    # strategy_config_builder.build_strategy_configs reading FieldDefinition/
    # FieldRef directly off each ExecutableModule.

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
    """

    application = "group_test"


    # ── Strategy parsing ───────────────────────────────────────

    def parse_strategy(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize a group-test strategy config.

        Expected config keys:
          - membership_index: int
          - group_id: str
          - display_name: str (or group_name)
          - initial_capital: float
          - ...other settings
        """
        parsed: dict[str, Any] = dict(config)
        parsed.setdefault("strategy_id", config.get("group_id", ""))
        parsed.setdefault("display_name", config.get("group_name") or config.get("group_id", ""))
        parsed.setdefault("strategy_kind", "group")
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
            "volume_capacity",
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
            entry: dict[str, Any] = {"key": key, "label": str(phase["label"])}
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
          - ...other settings (inherited from source group)
        """
        parsed: dict[str, Any] = dict(config)
        parsed.setdefault("strategy_id", config.get("name", ""))
        parsed.setdefault("display_name", config.get("name", ""))
        parsed.setdefault("strategy_kind", "long_short")
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
            "volume_capacity",
            "margin",
            "order_sizing",
            "cash_rescale",
        )


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

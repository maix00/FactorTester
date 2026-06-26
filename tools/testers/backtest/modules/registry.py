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

        # 2) Settings-derived params — forward a group_settings key only if it
        #    is both (a) a GROUP_ONLY/GROUP_OVERRIDE setting and (b) an actual
        #    _FactorGroupTestGroup constructor field. Most GROUP_OVERRIDE
        #    settings (order_execution, slippage, target_allocation, ...) are
        #    consumed by their own executable module's build_group_params
        #    (step 1) or read directly from group_settings at run time — they
        #    are not _FactorGroupTestGroup fields, and forwarding them blindly
        #    raises TypeError on construction. LOCAL_ONLY settings (e.g.
        #    engine) are page/run-level, already extracted separately via
        #    collect_local_only_settings.
        import dataclasses
        from tools.factors.tester_calc.single_factor_test.group import _FactorGroupTestGroup
        from tools.testers.settings.contracts import ScopePolicy
        group_fields = {f.name for f in dataclasses.fields(_FactorGroupTestGroup)}
        app = self.get_app()
        for key, setting in app.settings.items():
            if setting.scope_policy == ScopePolicy.LOCAL_ONLY:
                continue
            if key not in group_fields:
                continue
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

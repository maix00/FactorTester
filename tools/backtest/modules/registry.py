"""ModuleRegistry — unified entry point for executable modules, setting schemas,
and strategy parsing.

Inheritance chain:
    ModuleRegistry                    — base: collects ExecutableModules, produces module manifest
        BacktestModuleRegistry        — adds ApplicationSettings, produces full frontend manifest
            GroupTestModuleRegistry   — group-test modules + group strategy parsing
            LongShortModuleRegistry   — long-short modules + LS strategy parsing

Every module self-registers (no hardcoding in orchestrators or server endpoints).
The frontend receives the manifest from the registry — it knows nothing about
individual module files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ExecutableModule
from .fee import FeeModule
from .slippage import SlippageModule
from .liquidity import LiquidityModule
from .margin import MarginModule
from .position_sizing import PositionSizingModule
from .cash_rescale import CashRescaleModule


# ── Module manifest entries ───────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ModuleManifestEntry:
    """Self-describing entry for a single executable module."""
    key: str
    label: str
    order: int
    phases: tuple[dict[str, Any], ...]  # PhaseHandler → dict

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "order": self.order,
            "phases": self.phases,
        }


# ── All known ExecutableModule subclasses ─────────────────────────

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


# ── ModuleRegistry (base) ─────────────────────────────────────────


class ModuleRegistry:
    """Collects ExecutableModule subclasses and produces a module manifest.

    This is the base registry — it knows about executable modules only
    (no settings schema, no strategy parsing).
    """

    application: str = ""

    def __init__(self) -> None:
        self._module_classes: dict[str, type[ExecutableModule]] = _module_class_by_key()

    # ── module discovery ───────────────────────────────────────

    @property
    def module_keys(self) -> tuple[str, ...]:
        return tuple(self._module_classes.keys())

    def get_module_class(self, key: str) -> type[ExecutableModule]:
        try:
            return self._module_classes[key]
        except KeyError:
            raise KeyError(f"unknown executable module: {key!r}") from None

    def instantiate_all(self) -> list[ExecutableModule]:
        """Create one instance of every registered module."""
        return [cls() for cls in self._module_classes.values()]

    def instantiate(self, *keys: str) -> list[ExecutableModule]:
        """Create instances for the requested module keys (in given order)."""
        return [self.get_module_class(key)() for key in keys]

    # ── manifest ───────────────────────────────────────────────

    def module_manifest(self) -> list[dict[str, Any]]:
        """Return a list of module manifest dicts for the frontend.

        Each module's `phases` (PhaseHandler) declares what it needs/produces.
        """
        entries: list[dict[str, Any]] = []
        for cls in sorted(self._module_classes.values(), key=lambda c: c.order):
            phases = []
            for ph in cls.phases:
                phases.append({
                    "phase": ph.phase,
                    "order": ph.order,
                    "before": list(ph.before),
                    "after": list(ph.after),
                    "needs": list(ph.needs),
                    "produces": list(ph.produces),
                    "records": list(ph.records),
                })
            entries.append({
                "key": cls.key,
                "label": cls.label,
                "order": cls.order,
                "phases": phases,
            })
        return entries


# ── BacktestModuleRegistry ────────────────────────────────────────

# Import at runtime to avoid circular imports
def _get_backtest_setting_registry():
    from tools.backtest.settings import backtest_setting_registry
    return backtest_setting_registry


class BacktestModuleRegistry(ModuleRegistry):
    """Adds ApplicationSettings and produces a combined frontend manifest.

    The manifest merges:
      - Settings schema from ApplicationSettings (tabs, settings, chips, etc.)
      - Executable module info from ModuleRegistry

    Strategy parsing is deferred to subclasses (GroupTest / LongShort).
    """

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

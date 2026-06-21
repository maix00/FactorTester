"""Capability-first bridge from FactorTester signals to external frameworks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Framework(str, Enum):
    NATIVE = "native"
    BACKTRADER = "backtrader"
    QLIB = "qlib"
    ZIPLINE = "zipline"


class FrameworkFeature(str, Enum):
    PRECOMPUTED_SIGNALS = "precomputed_signals"
    TARGET_WEIGHTS = "target_weights"
    ISOLATED_MULTI_STRATEGY = "isolated_multi_strategy"
    PARTIAL_FILLS = "partial_fills"
    FUTURES_MARGIN = "futures_margin"
    DAILY_SETTLEMENT = "daily_settlement"
    CLOSE_TODAY_FEES = "close_today_fees"


class UnsupportedFrameworkPlan(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    framework: Framework
    native: frozenset[FrameworkFeature]
    extension_required: frozenset[FrameworkFeature]
    missing: frozenset[FrameworkFeature]

    @property
    def executable(self) -> bool:
        return not self.missing


@dataclass(frozen=True, slots=True)
class FrameworkCapabilities:
    framework: Framework
    native: frozenset[FrameworkFeature]
    extension_points: frozenset[FrameworkFeature] = frozenset()

    def report(self, required: frozenset[FrameworkFeature]) -> CapabilityReport:
        extension_required = (required - self.native) & self.extension_points
        missing = required - self.native - self.extension_points
        return CapabilityReport(
            self.framework,
            native=required & self.native,
            extension_required=extension_required,
            missing=missing,
        )


@dataclass(frozen=True, slots=True)
class SignalBridgeRequest:
    factor_alias: str
    signals: pd.DataFrame
    strategy_ids: tuple[str, ...]
    required_features: frozenset[FrameworkFeature]

    def __post_init__(self) -> None:
        if not self.factor_alias or self.signals.empty:
            raise ValueError("signal bridge requires factor alias and signal values")
        if not isinstance(self.signals.index, pd.DatetimeIndex):
            raise ValueError("signal bridge requires a DatetimeIndex")
        if not self.signals.index.is_unique or not self.signals.index.is_monotonic_increasing:
            raise ValueError("signal timestamps must be unique and monotonic")
        if not self.signals.columns.is_unique:
            raise ValueError("signal instruments must be unique")
        if not self.strategy_ids or len(set(self.strategy_ids)) != len(self.strategy_ids):
            raise ValueError("strategy_ids must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class SignalBridgePlan:
    framework: Framework
    factor_alias: str
    signals: pd.DataFrame
    strategy_ids: tuple[str, ...]
    capability_report: CapabilityReport


class SignalFrameworkAdapter:
    """Prepare a portable signal plan; framework packages execute it later."""

    def __init__(self, capabilities: FrameworkCapabilities) -> None:
        self.capabilities = capabilities

    def prepare(self, request: SignalBridgeRequest) -> SignalBridgePlan:
        report = self.capabilities.report(request.required_features)
        if report.missing:
            missing = ", ".join(sorted(feature.value for feature in report.missing))
            raise UnsupportedFrameworkPlan(
                f"{self.capabilities.framework.value} cannot represent: {missing}"
            )
        return SignalBridgePlan(
            framework=self.capabilities.framework,
            factor_alias=request.factor_alias,
            signals=request.signals,
            strategy_ids=request.strategy_ids,
            capability_report=report,
        )


NATIVE_CAPABILITIES = FrameworkCapabilities(
    Framework.NATIVE,
    native=frozenset(FrameworkFeature),
)

BACKTRADER_CAPABILITIES = FrameworkCapabilities(
    Framework.BACKTRADER,
    native=frozenset({
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.TARGET_WEIGHTS,
        FrameworkFeature.PARTIAL_FILLS,
    }),
    extension_points=frozenset({
        FrameworkFeature.ISOLATED_MULTI_STRATEGY,
        FrameworkFeature.FUTURES_MARGIN,
        FrameworkFeature.DAILY_SETTLEMENT,
        FrameworkFeature.CLOSE_TODAY_FEES,
    }),
)

QLIB_CAPABILITIES = FrameworkCapabilities(
    Framework.QLIB,
    native=frozenset({
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.TARGET_WEIGHTS,
        FrameworkFeature.PARTIAL_FILLS,
    }),
    extension_points=frozenset({FrameworkFeature.ISOLATED_MULTI_STRATEGY}),
)

ZIPLINE_CAPABILITIES = FrameworkCapabilities(
    Framework.ZIPLINE,
    native=frozenset({
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.TARGET_WEIGHTS,
        FrameworkFeature.PARTIAL_FILLS,
    }),
    extension_points=frozenset({
        FrameworkFeature.ISOLATED_MULTI_STRATEGY,
        FrameworkFeature.FUTURES_MARGIN,
        FrameworkFeature.DAILY_SETTLEMENT,
    }),
)


def built_in_adapters() -> dict[Framework, SignalFrameworkAdapter]:
    return {
        capabilities.framework: SignalFrameworkAdapter(capabilities)
        for capabilities in (
            NATIVE_CAPABILITIES,
            BACKTRADER_CAPABILITIES,
            QLIB_CAPABILITIES,
            ZIPLINE_CAPABILITIES,
        )
    }

"""Capability-first bridge from FactorTester factors to external frameworks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import pandas as pd


class Framework(str, Enum):
    NATIVE = "native"
    BACKTRADER = "backtrader"
    QLIB = "qlib"
    ZIPLINE = "zipline"
    RQALPHA = "rqalpha"


class FrameworkFeature(str, Enum):
    PRECOMPUTED_SIGNALS = "precomputed_signals"
    INCREMENTAL_FACTORS = "incremental_factors"
    TARGET_WEIGHTS = "target_weights"
    ISOLATED_MULTI_STRATEGY = "isolated_multi_strategy"
    PARTIAL_FILLS = "partial_fills"
    FUTURES_MARGIN = "futures_margin"
    DAILY_SETTLEMENT = "daily_settlement"
    CLOSE_TODAY_FEES = "close_today_fees"
    MARKET_ORDERS = "market_orders"
    LIMIT_ORDERS = "limit_orders"
    VOLUME_LIMIT_MATCHING = "volume_limit_matching"
    LOT_ROUNDING = "lot_rounding"
    MINOR_UNIT_ACCOUNTING = "minor_unit_accounting"


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
class PrecomputedFactorSource:
    signals: pd.DataFrame
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.signals.empty:
            raise ValueError("precomputed factor source requires signal values")
        if not isinstance(self.signals.index, pd.DatetimeIndex):
            raise ValueError("precomputed signals require a DatetimeIndex")
        if not self.signals.index.is_unique or not self.signals.index.is_monotonic_increasing:
            raise ValueError("signal timestamps must be unique and monotonic")
        if not self.signals.columns.is_unique:
            raise ValueError("signal instruments must be unique")
        if not isinstance(self.provenance, Mapping):
            raise TypeError("precomputed factor provenance must be a mapping")

    @classmethod
    def from_artifact(cls, artifact: Any) -> "PrecomputedFactorSource":
        signals = getattr(artifact, "signals", None)
        provenance = getattr(artifact, "provenance", None)
        if not isinstance(signals, pd.DataFrame) or not isinstance(provenance, Mapping):
            raise TypeError("artifact must expose signals DataFrame and provenance mapping")
        return cls(signals=signals, provenance=dict(provenance))


@dataclass(frozen=True, slots=True)
class IncrementalFactorSource:
    """A FactorExpr or compiled plan that executes inside the target framework."""

    factor_plan: object

    def __post_init__(self) -> None:
        if self.factor_plan is None:
            raise ValueError("incremental factor source requires a factor plan")


FactorSource = PrecomputedFactorSource | IncrementalFactorSource


@dataclass(frozen=True, slots=True)
class FactorBridgeRequest:
    factor_alias: str
    factor_source: FactorSource
    strategy_ids: tuple[str, ...]
    required_features: frozenset[FrameworkFeature]

    def __post_init__(self) -> None:
        if not self.factor_alias:
            raise ValueError("factor bridge requires a factor alias")
        if not self.strategy_ids or len(set(self.strategy_ids)) != len(self.strategy_ids):
            raise ValueError("strategy_ids must be non-empty and unique")

    @property
    def effective_required_features(self) -> frozenset[FrameworkFeature]:
        factor_feature = (
            FrameworkFeature.PRECOMPUTED_SIGNALS
            if isinstance(self.factor_source, PrecomputedFactorSource)
            else FrameworkFeature.INCREMENTAL_FACTORS
        )
        return self.required_features | {factor_feature}


@dataclass(frozen=True, slots=True)
class FactorBridgePlan:
    framework: Framework
    factor_alias: str
    factor_source: FactorSource
    strategy_ids: tuple[str, ...]
    capability_report: CapabilityReport


class FactorFrameworkAdapter:
    """Prepare a portable factor plan; framework packages execute it later."""

    def __init__(self, capabilities: FrameworkCapabilities) -> None:
        self.capabilities = capabilities

    def prepare(self, request: FactorBridgeRequest) -> FactorBridgePlan:
        report = self.capabilities.report(request.effective_required_features)
        if report.missing:
            missing = ", ".join(sorted(feature.value for feature in report.missing))
            raise UnsupportedFrameworkPlan(
                f"{self.capabilities.framework.value} cannot represent: {missing}"
            )
        return FactorBridgePlan(
            framework=self.capabilities.framework,
            factor_alias=request.factor_alias,
            factor_source=request.factor_source,
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
        FrameworkFeature.INCREMENTAL_FACTORS,
    }),
)

QLIB_CAPABILITIES = FrameworkCapabilities(
    Framework.QLIB,
    native=frozenset({
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.TARGET_WEIGHTS,
        FrameworkFeature.PARTIAL_FILLS,
    }),
    extension_points=frozenset({
        FrameworkFeature.ISOLATED_MULTI_STRATEGY,
        FrameworkFeature.INCREMENTAL_FACTORS,
    }),
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
        FrameworkFeature.INCREMENTAL_FACTORS,
    }),
)

RQALPHA_CAPABILITIES = FrameworkCapabilities(
    Framework.RQALPHA,
    native=frozenset({
        FrameworkFeature.PRECOMPUTED_SIGNALS,
        FrameworkFeature.TARGET_WEIGHTS,
        FrameworkFeature.MARKET_ORDERS,
        FrameworkFeature.LIMIT_ORDERS,
        FrameworkFeature.LOT_ROUNDING,
    }),
    extension_points=frozenset({
        FrameworkFeature.ISOLATED_MULTI_STRATEGY,
        FrameworkFeature.FUTURES_MARGIN,
        FrameworkFeature.DAILY_SETTLEMENT,
        FrameworkFeature.CLOSE_TODAY_FEES,
        FrameworkFeature.INCREMENTAL_FACTORS,
        FrameworkFeature.VOLUME_LIMIT_MATCHING,
    }),
)


def built_in_adapters() -> dict[Framework, FactorFrameworkAdapter]:
    return {
        capabilities.framework: FactorFrameworkAdapter(capabilities)
        for capabilities in (
            NATIVE_CAPABILITIES,
            BACKTRADER_CAPABILITIES,
            QLIB_CAPABILITIES,
            ZIPLINE_CAPABILITIES,
            RQALPHA_CAPABILITIES,
        )
    }

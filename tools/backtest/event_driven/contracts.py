"""Canonical contracts shared by research, execution engines, and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import numpy as np
import pandas as pd


class ExecutionFeature(str, Enum):
    VECTOR_BATCH = "vector_batch"
    CLOCKED_STATE = "clocked_state"
    ASYNC_ORDERS = "async_orders"
    TRANSACTION_COSTS = "transaction_costs"
    LIQUIDITY = "liquidity"
    MARGIN = "margin"
    FUTURES = "futures"
    FUTURES_ROLL = "futures_roll"
    MULTI_CURRENCY = "multi_currency"
    STREAMING_FACTORS = "streaming_factors"


class TargetKind(str, Enum):
    WEIGHT = "weight"
    QUANTITY = "quantity"


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Correlation identity; it contains no credentials or user payloads."""

    run_id: str
    user_id: str | None = None
    page_uuid: str | None = None
    session_id: str | None = None
    tester_alias: str | None = None


@dataclass(frozen=True, slots=True)
class BacktestPlan:
    """Portable description of what an execution engine must support."""

    identity: RunIdentity
    timestamps: pd.DatetimeIndex
    instruments: tuple[str, ...]
    required_features: frozenset[ExecutionFeature] = frozenset()
    factor_plan: Any | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.identity.run_id:
            raise ValueError("run_id must not be empty")
        if self.timestamps.empty:
            raise ValueError("timestamps must not be empty")
        if not self.timestamps.is_monotonic_increasing:
            raise ValueError("timestamps must be monotonic increasing")
        if not self.instruments or len(set(self.instruments)) != len(self.instruments):
            raise ValueError("instruments must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class PortfolioIntent:
    """Strategy output. Execution engines own order and fill generation."""

    timestamp: pd.Timestamp
    strategy_id: str
    portfolio_id: str
    target_kind: TargetKind
    values: np.ndarray
    instruments: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.portfolio_id:
            raise ValueError("strategy_id and portfolio_id must not be empty")
        values = np.asarray(self.values, dtype=float)
        if values.ndim not in (1, 2) or values.shape[-1] != len(self.instruments):
            raise ValueError("intent values must end with the instrument axis")
        if not np.all(np.isfinite(values)):
            raise ValueError("intent values must be finite")
        object.__setattr__(self, "values", values)


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class FeeComponent:
    """One named fee component, expressed in base-currency minor units."""

    name: str
    amount_minor: int

    def __post_init__(self) -> None:
        if not self.name or self.amount_minor < 0:
            raise ValueError("fee component requires a name and non-negative amount")


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    """Fees frozen onto a fill so replay never queries mutable fee schedules."""

    components: tuple[FeeComponent, ...] = ()

    def __post_init__(self) -> None:
        names = [component.name for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError("fee component names must be unique")

    @property
    def total_minor(self) -> int:
        return sum(component.amount_minor for component in self.components)


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    strategy_id: str
    portfolio_id: str
    timestamp: pd.Timestamp
    instrument: str
    side: OrderSide
    quantity: float

    def __post_init__(self) -> None:
        if (
            not self.order_id
            or not self.strategy_id
            or not self.portfolio_id
            or not self.instrument
            or self.quantity <= 0
        ):
            raise ValueError("order requires id, instrument, and positive quantity")


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    order_id: str
    strategy_id: str
    portfolio_id: str
    timestamp: pd.Timestamp
    instrument: str
    side: OrderSide
    quantity: float
    price: float
    fees: FeeBreakdown = field(default_factory=FeeBreakdown)

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("fill quantity and price must be positive")


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    timestamp: pd.Timestamp
    cash_minor: np.ndarray
    equity_minor: np.ndarray
    quantities: np.ndarray


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Engine-neutral result; framework-specific objects stay in diagnostics."""

    identity: RunIdentity
    engine: str
    snapshots: tuple[LedgerSnapshot, ...]
    fills: tuple[Fill, ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

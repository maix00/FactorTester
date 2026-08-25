"""Explicit public SDK contract for factor authors.

This module is the only place that decides which ``tools`` stubs enter a
factor workspace. Runtime imports and implementation dependencies must not
expand this list implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorSdkModule:
    destination: str
    source: str | None = None
    content: str | None = None
    prelude: str = ""
    footer: str = ""


_HEADER = "from __future__ import annotations\nfrom typing import Any\n\n"


AUTHOR_SDK_MODULES = (
    AuthorSdkModule(
        "pandas/__init__.pyi",
        content=_HEADER
        + "class DataFrame: ...\n"
        + "class Series: ...\n"
        + "class Timestamp:\n    def __new__(cls, value: Any = ...) -> Timestamp: ...\n"
        + "class Timedelta:\n    def __new__(cls, value: Any = ...) -> Timedelta: ...\n",
    ),
    AuthorSdkModule(
        "tools/__init__.pyi",
        content=_HEADER.rstrip() + "\n",
    ),
    AuthorSdkModule("tools/data/__init__.pyi", content=_HEADER),
    AuthorSdkModule("tools/testers/__init__.pyi", content=_HEADER),
    AuthorSdkModule("tools/testers/backtest/__init__.pyi", content=_HEADER),
    AuthorSdkModule("tools/testers/backtest/modules/__init__.pyi", content=_HEADER),
    AuthorSdkModule(
        "tools/testers/backtest/modules/strategy_book.pyi",
        content=_HEADER
        + "from dataclasses import dataclass, field\n"
        + "from typing import Callable, Literal\n\n"
        + "OrderRoutingPolicy = Callable[[Any, Any], str | Any]\n"
        + "CashAvailabilityPolicy = Callable[[Any, Any, float, str], float]\n"
        + "OrderSizingPolicy = Callable[[Any, Any, Any, dict[Any, float]], dict[Any, float]]\n"
        + "PendingOrderConflictPolicy = Callable[[Any, Any, Any, Any], None]\n"
        + "TradeDecisionMergePolicy = Callable[[Any, Any, list[Any]], Any]\n"
        + "HierarchyConstraintPolicy = Callable[[Any, Any, Any], Any]\n"
        + "StrategyIntentPrecomputePolicy = Callable[[Any, list[Any]], Any]\n\n"
        + "class StrategyIntentPolicy:\n"
        + "    def generate_strategy_intents(self, state: Any, ctx: Any, strategies: list[Any]) -> None: ...\n"
        + "    def precompute_strategy_intents(self, state: Any, ctx: Any, strategies: list[Any]) -> None: ...\n\n"
        + "@dataclass(frozen=True)\n"
        + "class LedgerConfig:\n"
        + "    ledger: Any\n"
        + "    cash_pool: Any | None = ...\n"
        + "    counterparty_profile_id: str | None = ...\n\n"
        + "@dataclass(frozen=True)\n"
        + "class StrategyBookPolicies:\n"
        + "    order_routing: OrderRoutingPolicy | None = ...\n"
        + "    cash_availability: CashAvailabilityPolicy | None = ...\n"
        + "    order_sizing: OrderSizingPolicy | None = ...\n"
        + "    pending_order_conflict: PendingOrderConflictPolicy | None = ...\n"
        + "    trade_decision_merge: TradeDecisionMergePolicy | None = ...\n"
        + "    hierarchy_constraints: HierarchyConstraintPolicy | None = ...\n"
        + "    strategy_intent_by_alias: dict[str, StrategyIntentPolicy] = ...\n"
        + "    strategy_intent_precompute: StrategyIntentPrecomputePolicy | None = ...\n\n"
        + "@dataclass\n"
        + "class StrategyBook:\n"
        + "    mode: str = ...\n"
        + "    policies: StrategyBookPolicies = ...\n"
        + "    ledger_configs: dict[Any, LedgerConfig] = ...\n"
        + "    default_ledger_by_strategy: dict[Any, Any] = ...\n"
        + "    ledgers_by_strategy: dict[Any, tuple[Any, ...]] = ...\n"
        + "    @classmethod\n    def from_dict(cls, payload: dict[str, Any] | None) -> StrategyBook: ...\n"
        + "    def ledger_id_for_order(self, state: Any, order: Any) -> Any: ...\n"
        + "    def default_ledger_id_for_strategy(self, state: Any, strategy: Any) -> Any: ...\n"
        + "    def ledger_ids_for_strategy(self, state: Any, strategy: Any) -> tuple[Any, ...]: ...\n",
    ),
    AuthorSdkModule(
        "tools/testers/backtest/modules/volume_capacity.pyi",
        content=_HEADER
        + "from typing import Literal\n\n"
        + "class VolumeCapacityMode:\n"
        + "    mode: Literal['infinite', 'volume_participation', 'custom']\n"
        + "    participation_rate: float\n"
        + "    def __init__(self, mode: str = ..., participation_rate: float = ...) -> None: ...\n\n"
        + "def volume_capacity_from_config(config: Any) -> VolumeCapacityMode: ...\n"
        + "def apply_volume_capacity_policy(deltas: dict[Any, float], volumes: dict[Any, float], capacity: VolumeCapacityMode) -> dict[Any, float]: ...\n",
    ),
    AuthorSdkModule(
        "tools/data/types/__init__.pyi",
        content=_HEADER
        + "class DataColumn:\n"
        + "    OPEN: DataColumn\n    HIGH: DataColumn\n    LOW: DataColumn\n    CLOSE: DataColumn\n"
        + "    VOLUME: DataColumn\n    TURNOVER: DataColumn\n    OPEN_INTEREST: DataColumn\n"
        + "    TWAP: DataColumn\n    VWAP: DataColumn\n    SETTLEMENT_PRICE: DataColumn\n"
        + "    OPEN_ADJUSTED: DataColumn\n    HIGH_ADJUSTED: DataColumn\n"
        + "    LOW_ADJUSTED: DataColumn\n    CLOSE_ADJUSTED: DataColumn\n\n"
        + "class DataFreq:\n"
        + "    value: Any\n    name: str\n    alias: str\n"
        + "    MIN1: DataFreq\n    MIN5: DataFreq\n    MIN15: DataFreq\n    MIN30: DataFreq\n"
        + "    HOUR1: DataFreq\n    DAY1: DataFreq\n"
        + "    def __new__(cls, freq: Any) -> DataFreq: ...\n"
        + "    @property\n    def days(self) -> int: ...\n"
        + "    @property\n    def is_multiples_of_day(self) -> bool: ...\n\n"
        + "class DataTime:\n"
        + "    @classmethod\n    def parse(cls, value: Any = ..., *, precision: str = ..., tz: str | None = ...) -> DataTime: ...\n"
        + "\nclass UniqueNameObject:\n"
        + "    name: str\n    alias: str\n",
    ),
    AuthorSdkModule(
        "tools/factors/__init__.pyi",
        content=_HEADER
        + "from tools.factors.FactorFamily import FactorFamily as FactorFamily\n"
        + "from tools.factors.Factors import Factor as Factor\n"
        + "from tools.factors.FactorExpr import (\n"
        + "    FactorExpr as FactorExpr, ConstExpr as ConstExpr, ParamRef as ParamRef,\n"
        + "    ColumnRef as ColumnRef, expr_max as expr_max, expr_min as expr_min,\n"
        + "    where as where,\n"
        + "    term_spread as term_spread, term_ratio as term_ratio, term_slope as term_slope,\n"
        + "    SMALL_VAL as SMALL_VAL,\n"
        + ")\n"
        + "from tools.factors.Parameters import (\n"
        + "    FactorNextPeriodReturns as FactorNextPeriodReturns, ReturnFreqParam as ReturnFreqParam,\n"
        + "    FactorFreqParam as FactorFreqParam,\n"
        + "    ReverseParam as ReverseParam,\n"
        + ")\n",
    ),
    AuthorSdkModule(
        "tools/factors/FactorFamily.pyi",
        source="tools/factors/FactorFamily.py",
        prelude=(
            "import threading\nimport pandas as pd\n"
            "from typing import Callable, Dict, List, Optional\n"
            "from tools.data.types import DataFreq, UniqueNameObject\n"
            "from tools.factors.FactorExpr import FactorExpr\n"
            "from tools.parameters import Parameter\n"
            "Factor = Any\n"
        ),
    ),
    AuthorSdkModule(
        "tools/factors/Factors.pyi",
        source="tools/factors/Factors.py",
        prelude=(
            "import pandas as pd\n"
            "from typing import Dict, Optional, Set, Tuple, Union\n"
            "from tools.data.types import DataFreq, UniqueNameObject\n"
            "from tools.factors.FactorExpr import FactorExpr\n"
            "FactorFamily = Any\n"
            "Product = Any\n"
        ),
    ),
    AuthorSdkModule(
        "tools/factors/expr/__init__.pyi",
        content=_HEADER
        + "from tools.factors.expr.core import FactorExpr as FactorExpr\n"
        + "from tools.factors.FactorExpr import where as where\n",
    ),
    AuthorSdkModule(
        "tools/factors/expr/core.pyi",
        source="tools/factors/expr/core.py",
        prelude=(
            "# pyright: reportIncompatibleMethodOverride=false\n"
            "import pandas as pd\n"
            "from typing import Optional, TypeAlias, Union\n"
            "from tools.parameters import Parameter\n"
        ),
        footer=(
            "class RollingExpr(FactorExpr):\n"
            "    @property\n    def bars(self) -> FactorExpr: ...\n"
            "    def truncate(self, start: Any, end: Any) -> RollingExpr: ...\n"
            "    def mean(self) -> FactorExpr: ...\n"
            "    def std(self) -> FactorExpr: ...\n"
            "    def var(self) -> FactorExpr: ...\n"
            "    def min(self) -> FactorExpr: ...\n"
            "    def max(self) -> FactorExpr: ...\n"
            "    def sum(self) -> FactorExpr: ...\n"
            "    def ema(self) -> FactorExpr: ...\n"
            "    def skew(self) -> FactorExpr: ...\n"
            "    def argmax(self) -> FactorExpr: ...\n"
            "    def argmin(self) -> FactorExpr: ...\n"
            "    def argmax_raw(self) -> FactorExpr: ...\n"
            "    def argmin_raw(self) -> FactorExpr: ...\n"
            "    def corr(self, other: Any) -> FactorExpr: ...\n"
            "    def cov(self, other: Any) -> FactorExpr: ...\n"
            "RollingOp: TypeAlias = FactorExpr\n"
            "ShiftOp: TypeAlias = FactorExpr\n"
            "CrossSectionalOp: TypeAlias = FactorExpr\n"
        ),
    ),
    AuthorSdkModule(
        "tools/factors/FactorExpr.pyi",
        content=_HEADER
        + "from tools.data.types import DataColumn, DataFreq\n"
        + "from tools.factors.expr.core import FactorExpr as FactorExpr\n\n"
        + "class OperandExpr(FactorExpr): ...\n"
        + "class ColumnRef(FactorExpr):\n    def __init__(self, column: DataColumn) -> None: ...\n"
        + "class ParamRef(FactorExpr): ...\n"
        + "class ConstExpr(FactorExpr):\n    def __init__(self, value: Any) -> None: ...\n"
        + "class CompositeExpr(FactorExpr): ...\n"
        + "class WindowBarsExpr(FactorExpr): ...\n"
        + "class WhereOp(FactorExpr): ...\n"
        + "class ShiftOp(FactorExpr): ...\n"
        + "class CrossSectionalOp(FactorExpr): ...\n"
        + "class TermStructureOp(FactorExpr): ...\n"
        + "class SignalAlign(FactorExpr): ...\n\n"
        + "def expr_max(*expressions: Any) -> FactorExpr: ...\n"
        + "def expr_min(*expressions: Any) -> FactorExpr: ...\n"
        + "def where(condition: Any, true_value: Any, false_value: Any = ...) -> FactorExpr: ...\n"
        + "def window_bars(window: Any) -> WindowBarsExpr: ...\n"
        + "def term_spread(*args: Any, **kwargs: Any) -> FactorExpr: ...\n"
        + "def term_ratio(*args: Any, **kwargs: Any) -> FactorExpr: ...\n"
        + "def term_slope(*args: Any, **kwargs: Any) -> FactorExpr: ...\n\n"
        + "OPEN: ColumnRef\nHIGH: ColumnRef\nLOW: ColumnRef\nCLOSE: ColumnRef\n"
        + "VOLUME: ColumnRef\nTURNOVER: ColumnRef\nOPEN_INTEREST: ColumnRef\n"
        + "VWAP: ColumnRef\nSETTLE: ColumnRef\nOPEN_RAW: ColumnRef\nHIGH_RAW: ColumnRef\n"
        + "LOW_RAW: ColumnRef\nCLOSE_RAW: ColumnRef\nSMALL_VAL: ConstExpr\n",
    ),
    AuthorSdkModule(
        "tools/factors/Parameters.pyi",
        source="tools/factors/Parameters.py",
        prelude=(
            "from enum import Enum\n"
            "from tools.parameters.Parameter import Parameter\n"
        ),
    ),
    AuthorSdkModule(
        "tools/parameters/__init__.pyi",
        content=_HEADER
        + "from tools.parameters.Parameter import (\n"
        + "    Parameter as Parameter, TypeParam as TypeParam, FinRangeParam as FinRangeParam,\n"
        + "    TimeDeltaParam as TimeDeltaParam, FactorParam as FactorParam, ValueSpace as ValueSpace,\n"
        + ")\n"
        + "from tools.parameters.DataColumnParam import DataColumnParam as DataColumnParam\n"
        + "from tools.parameters.DataTimeParam import DataTimeParam as DataTimeParam\n"
        + "from tools.parameters.WindowParam import WindowParam as WindowParam\n",
    ),
    AuthorSdkModule(
        "tools/parameters/Parameter.pyi",
        source="tools/parameters/Parameter.py",
        prelude=(
            "from typing import Callable, List, Optional\n"
            "from tools.data.types import UniqueNameObject\n"
        ),
    ),
    AuthorSdkModule(
        "tools/parameters/DataColumnParam.pyi",
        source="tools/parameters/DataColumnParam.py",
        prelude="from typing import Optional\nfrom tools.parameters.Parameter import Parameter\n",
    ),
    AuthorSdkModule(
        "tools/parameters/DataTimeParam.pyi",
        source="tools/parameters/DataTimeParam.py",
        prelude="from typing import Optional\nfrom tools.parameters.Parameter import Parameter\n",
    ),
    AuthorSdkModule(
        "tools/parameters/WindowParam.pyi",
        source="tools/parameters/WindowParam.py",
        prelude="from typing import Optional\nfrom tools.parameters.Parameter import Parameter\n",
    ),
)


def author_sdk_paths() -> frozenset[str]:
    return frozenset(module.destination for module in AUTHOR_SDK_MODULES)

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


_HEADER = "from __future__ import annotations\nfrom typing import Any\n\n"


AUTHOR_SDK_MODULES = (
    AuthorSdkModule(
        "tools/__init__.pyi",
        content=_HEADER + "from tools.factors import FactorFamily, FactorFreqParam\n",
    ),
    AuthorSdkModule("tools/data/__init__.pyi", content=_HEADER),
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
        + "    @classmethod\n    def parse(cls, value: Any = ..., *, precision: str = ..., tz: str | None = ...) -> DataTime: ...\n",
    ),
    AuthorSdkModule(
        "tools/factors/__init__.pyi",
        content=_HEADER
        + "from tools.factors.FactorFamily import FactorFamily\n"
        + "from tools.factors.Factors import Factor\n"
        + "from tools.factors.FactorExpr import FactorExpr, ConstExpr, ParamRef, ColumnRef, "
        + "expr_max, expr_min, term_spread, term_ratio, term_slope, SMALL_VAL\n"
        + "from tools.factors.Parameters import FactorNextPeriodReturns, ReturnFreqParam, "
        + "FactorFreqParam, StartCalcPointParam, ReverseParam\n",
    ),
    AuthorSdkModule("tools/factors/FactorFamily.pyi", source="tools/factors/FactorFamily.py"),
    AuthorSdkModule("tools/factors/Factors.pyi", source="tools/factors/Factors.py"),
    AuthorSdkModule("tools/factors/expr/__init__.pyi", content=_HEADER + "from tools.factors.expr.core import FactorExpr\n"),
    AuthorSdkModule("tools/factors/expr/core.pyi", source="tools/factors/expr/core.py"),
    AuthorSdkModule(
        "tools/factors/FactorExpr.pyi",
        content=_HEADER
        + "from tools.data.types import DataColumn, DataFreq\n"
        + "from tools.factors.expr.core import FactorExpr\n\n"
        + "class OperandExpr(FactorExpr): ...\n"
        + "class ColumnRef(FactorExpr):\n    def __init__(self, column: DataColumn) -> None: ...\n"
        + "class ParamRef(FactorExpr): ...\n"
        + "class ConstExpr(FactorExpr):\n    def __init__(self, value: Any) -> None: ...\n"
        + "class CompositeExpr(FactorExpr): ...\n"
        + "class ShiftOp(FactorExpr): ...\n"
        + "class CrossSectionalOp(FactorExpr): ...\n"
        + "class TermStructureOp(FactorExpr): ...\n"
        + "class SignalAlign(FactorExpr): ...\n\n"
        + "def expr_max(*expressions: Any) -> FactorExpr: ...\n"
        + "def expr_min(*expressions: Any) -> FactorExpr: ...\n"
        + "def term_spread(*args: Any, **kwargs: Any) -> FactorExpr: ...\n"
        + "def term_ratio(*args: Any, **kwargs: Any) -> FactorExpr: ...\n"
        + "def term_slope(*args: Any, **kwargs: Any) -> FactorExpr: ...\n\n"
        + "OPEN: ColumnRef\nHIGH: ColumnRef\nLOW: ColumnRef\nCLOSE: ColumnRef\n"
        + "VOLUME: ColumnRef\nTURNOVER: ColumnRef\nOPEN_INTEREST: ColumnRef\n"
        + "VWAP: ColumnRef\nSETTLE: ColumnRef\nOPEN_RAW: ColumnRef\nHIGH_RAW: ColumnRef\n"
        + "LOW_RAW: ColumnRef\nCLOSE_RAW: ColumnRef\nSMALL_VAL: ConstExpr\n",
    ),
    AuthorSdkModule("tools/factors/Parameters.pyi", source="tools/factors/Parameters.py"),
    AuthorSdkModule(
        "tools/parameters/__init__.pyi",
        content=_HEADER
        + "from tools.parameters.Parameter import Parameter, TypeParam, FinRangeParam, "
        + "TimeDeltaParam, FactorParam, ValueSpace\n"
        + "from tools.parameters.DataColumnParam import DataColumnParam\n"
        + "from tools.parameters.DataTimeParam import DataTimeParam\n"
        + "from tools.parameters.WindowParam import WindowParam\n",
    ),
    AuthorSdkModule("tools/parameters/Parameter.pyi", source="tools/parameters/Parameter.py"),
    AuthorSdkModule("tools/parameters/DataColumnParam.pyi", source="tools/parameters/DataColumnParam.py"),
    AuthorSdkModule("tools/parameters/DataTimeParam.pyi", source="tools/parameters/DataTimeParam.py"),
    AuthorSdkModule("tools/parameters/WindowParam.pyi", source="tools/parameters/WindowParam.py"),
)


def author_sdk_paths() -> frozenset[str]:
    return frozenset(module.destination for module in AUTHOR_SDK_MODULES)

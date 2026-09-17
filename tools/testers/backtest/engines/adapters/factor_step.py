"""Framework-neutral per-step execution of batch or incremental factor sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tools.factors.expr import ColumnRef, FactorExpr

from ..factors.events import FactorSignal


@dataclass(frozen=True, slots=True)
class ProductPrice:
    instrument: str
    price: float
    fields: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class MarketSlice:
    prices: Mapping[str, ProductPrice]
    # 运行时执行器传入的切片带时间；早期适配器只填 prices，故为可选。
    # 静态标注用字符串，避免依赖该文件里 pandas 的导入位置。
    timestamp: "pd.Timestamp | None" = None
    trading_day: "pd.Timestamp | None" = None

from ..factors.incremental import StreamingFactorPlan, compile_streaming_factor
from .frameworks import IncrementalFactorSource, PrecomputedFactorSource


def required_factor_columns(expression: FactorExpr) -> frozenset[str]:
    columns: set[str] = set()
    visited: set[int] = set()

    def visit(node: FactorExpr) -> None:
        if id(node) in visited:
            return
        visited.add(id(node))
        if isinstance(node, ColumnRef):
            columns.add(node.column.name)
        for operand in getattr(node, "_operands", ()):
            visit(operand)

    visit(expression)
    return frozenset(columns)


class FactorStepAdapter:
    """Execute one factor source at framework callback granularity."""

    def __init__(
        self,
        factor_alias: str,
        factor_source: PrecomputedFactorSource | IncrementalFactorSource,
        instruments: tuple[str, ...],
    ) -> None:
        if not factor_alias or not instruments:
            raise ValueError("factor step adapter requires alias and instruments")
        self.factor_alias = factor_alias
        self.factor_source = factor_source
        self.instruments = instruments
        self._streaming_plan: StreamingFactorPlan | None = None
        self.required_columns: frozenset[str] = frozenset()
        if isinstance(factor_source, IncrementalFactorSource):
            if not isinstance(factor_source.factor_plan, FactorExpr):
                raise TypeError("incremental factor plan must be a FactorExpr")
            self.required_columns = required_factor_columns(factor_source.factor_plan)
            self._streaming_plan = compile_streaming_factor(
                factor_source.factor_plan,
                instruments,
            )

    def update(
        self,
        timestamp: pd.Timestamp,
        fields: Mapping[str, Mapping[str, float]],
        trading_day: pd.Timestamp | None = None,
    ) -> FactorSignal:
        """``trading_day`` 必须来自权威来源（面板索引的 DAY1 层或运行时解析器）。

        仅凭这里的 timestamp 无法推出交易日（夜盘归属下一个交易日），所以不能由
        本适配器自行推断；作用域为 trading_day 的因子在缺少它时会显式报错。
        """
        timestamp = pd.Timestamp(timestamp)
        if isinstance(self.factor_source, PrecomputedFactorSource):
            row = self.factor_source.signals.loc[timestamp]
            return FactorSignal(
                self.factor_alias,
                {instrument: float(row[instrument]) for instrument in self.instruments},
            )
        market = MarketSlice(
            {
                instrument: ProductPrice(
                    instrument,
                    price=_reference_price(fields[instrument]),
                    fields=fields[instrument],
                )
                for instrument in self.instruments
            },
            timestamp=timestamp,
            trading_day=None if trading_day is None else pd.Timestamp(trading_day),
        )
        assert self._streaming_plan is not None
        return FactorSignal(
            self.factor_alias,
            self._streaming_plan.update(timestamp, market),
        )


def _reference_price(fields: Mapping[str, float]) -> float:
    close = fields.get("CLOSE", 1.0)
    if np.isfinite(close) and close > 0:
        return float(close)
    return 1.0

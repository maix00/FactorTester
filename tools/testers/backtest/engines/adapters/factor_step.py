"""Framework-neutral per-step execution of batch or incremental factor sources."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from tools.factors.expr import ColumnRef, FactorExpr

from ..factors.events import FactorSignal


def _issue114_missing(name: str):
    def _raise(*args, **kwargs):  # noqa: ANN001
        raise NotImplementedError(
            f"{name}: lived in the deleted engines/native/runtime.py "
            "(issue-114 Event/Order/Flow rewrite); backtrader-engine adapter "
            "bridging is explicitly out of scope this round (see plan)")
    return _raise


# MarketSlice/ProductPrice lived in engines/native/runtime.py, deleted in the
# issue-114 rewrite. This adapter bridges incremental factor streaming into
# the backtrader engine specifically — out of scope this round (plan: "不在
# 本轮范围内... backtrader/qlib/zipline 的事件驱动桥接"). Stubbed so this
# module stays importable; calling FactorStepAdapter.update() for the
# incremental path raises clearly instead of silently breaking elsewhere.
MarketSlice = _issue114_missing("MarketSlice")
ProductPrice = _issue114_missing("ProductPrice")
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
    ) -> FactorSignal:
        timestamp = pd.Timestamp(timestamp)
        if isinstance(self.factor_source, PrecomputedFactorSource):
            row = self.factor_source.signals.loc[timestamp]
            return FactorSignal(
                self.factor_alias,
                {instrument: float(row[instrument]) for instrument in self.instruments},
            )
        market = MarketSlice({
            instrument: ProductPrice(
                instrument,
                price=_reference_price(fields[instrument]),
                fields=fields[instrument],
            )
            for instrument in self.instruments
        })
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

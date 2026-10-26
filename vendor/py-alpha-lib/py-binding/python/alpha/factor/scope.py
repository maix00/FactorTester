"""Partitioned aggregation for the public factor API (Rust interval kernel)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .core import FactorExpr
from .semantics import NanPolicy, PartitionSemantics
from .scopes import SessionScope, TradingDayScope


@dataclass(frozen=True)
class BarCountScope:
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("bar-count scope must be positive")


def scope_bars(count: int) -> BarCountScope:
    return BarCountScope(int(count))


class GroupByScopeExpr(FactorExpr):
    def __init__(self, scope, data: FactorExpr,
                 semantics: PartitionSemantics | None = None):
        self.scope = scope
        self.data = data
        self.semantics = semantics or PartitionSemantics()

    def _structural_key(self):
        key = getattr(self.scope, "count", None) or type(self.scope).__name__
        return ("alpha.factor.GroupByScopeExpr", key,
                self.semantics.effective_min_periods,
                self.semantics.nan_policy.value,
                self.data._structural_key())

    def _aggregate(self, op: str, quantile: float | None = None) -> "GroupByScopeOp":
        return GroupByScopeOp(op, self)


class GroupByScopeOp(FactorExpr):
    def __init__(self, op: str, owner: GroupByScopeExpr):
        self.op = op
        self.owner = owner

    def evaluate(self, ctx):
        # Day/session partitions are resolved from the context calendar; the
        # matrix plan path currently covers bar-count scopes only.
        if not isinstance(self.owner.scope, BarCountScope):
            return self._evaluate(ctx)
        return super().evaluate(ctx)

    @property
    def days(self):
        return self.owner.days

    @property
    def times(self):
        return self.owner.times

    def _structural_key(self):
        return ("alpha.factor.GroupByScopeOp", self.op, self.owner._structural_key())

    def _evaluate(self, ctx) -> pd.DataFrame:
        frame = self.owner.data.evaluate(ctx)
        if ctx.trading_days is not None:
            self.owner.days = np.asarray(ctx.trading_days)
        else:
            self.owner.days = pd.factorize(frame.index.normalize())[0]
        self.owner.times = np.asarray(frame.index.asi8 if isinstance(frame.index, pd.DatetimeIndex) else np.arange(len(frame.index)))
        from alpha import interval_rolling
        starts = None
        output = {}
        for product in frame.columns:
            values = frame[product].to_numpy(dtype=float)
            ordinals = np.arange(len(values), dtype=np.uint64)
            if isinstance(self.owner.scope, BarCountScope):
                starts = (ordinals.astype(np.int64) // self.owner.scope.count * self.owner.scope.count).astype(np.uint64)
            elif isinstance(self.owner.scope, TradingDayScope):
                days = self.owner.days
                starts = np.zeros(len(values), dtype=np.uint64)
                current = 0
                for i in range(1, len(values)):
                    if days[i] != days[i - 1]:
                        current = i
                    starts[i] = current
            else:
                times = self.owner.times
                gap = self.owner.scope.gap_ns
                starts = np.zeros(len(values), dtype=np.uint64)
                current = 0
                for i in range(1, len(values)):
                    if times[i] - times[i - 1] >= gap:
                        current = i
                    starts[i] = current
            op, _, q = self.op.partition(":")
            output[product] = interval_rolling(
                values, starts, ordinals, op,
                float(q) if q else None, None,
                self.owner.semantics.effective_min_periods,
                self.owner.semantics.nan_policy is NanPolicy.PROPAGATE,
            )
        return pd.DataFrame(output, index=frame.index)


def _methods(cls: type) -> None:
    def groupby_scope(self, scope):
        return GroupByScopeExpr(scope, self)

    cls.groupby_scope = groupby_scope


_methods(FactorExpr)

for _name in ("mean", "sum", "std", "var", "min", "max", "median", "mad"):
    setattr(
        GroupByScopeExpr, _name,
        (lambda name: lambda self: self._aggregate(name))(_name),
    )


def _quantile(self, q: float):
    return self._aggregate(f"quantile:{float(q)}")


GroupByScopeExpr.quantile = _quantile

"""Partitioned aggregation for the public factor API (Rust interval kernel)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .core import FactorExpr
from .semantics import NanPolicy, PartitionSemantics


@dataclass(frozen=True)
class BarCountScope:
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("bar-count scope must be positive")


def scope_bars(count: int) -> BarCountScope:
    return BarCountScope(int(count))


class GroupByScopeExpr(FactorExpr):
    def __init__(self, scope: BarCountScope, data: FactorExpr,
                 semantics: PartitionSemantics | None = None):
        self.scope = scope
        self.data = data
        self.semantics = semantics or PartitionSemantics()

    def _structural_key(self):
        return ("alpha.factor.GroupByScopeExpr", self.scope.count,
                self.semantics.effective_min_periods,
                self.semantics.nan_policy.value,
                self.data._structural_key())

    def _aggregate(self, op: str, quantile: float | None = None) -> "GroupByScopeOp":
        return GroupByScopeOp(op, self)


class GroupByScopeOp(FactorExpr):
    def __init__(self, op: str, owner: GroupByScopeExpr):
        self.op = op
        self.owner = owner

    def _structural_key(self):
        return ("alpha.factor.GroupByScopeOp", self.op, self.owner._structural_key())

    def _evaluate(self, ctx) -> pd.DataFrame:
        frame = self.owner.data.evaluate(ctx)
        from alpha import interval_rolling
        starts = None
        output = {}
        for product in frame.columns:
            values = frame[product].to_numpy(dtype=float)
            ordinals = np.arange(len(values), dtype=np.uint64)
            starts = (ordinals.astype(np.int64) // self.owner.scope.count * self.owner.scope.count).astype(np.uint64)
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

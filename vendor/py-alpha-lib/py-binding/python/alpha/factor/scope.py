"""Partitioned aggregation for the public factor API (Rust interval kernel)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .core import FactorExpr
from .semantics import PartitionSemantics
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
        key = (("bars", self.scope.count) if isinstance(self.scope, BarCountScope) else
               (type(self.scope).__name__, tuple((item.start_ns, item.end_ns, repr(item.trading_day))
                                                for item in self.scope.sessions)))
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

    def _structural_key(self):
        return ("alpha.factor.GroupByScopeOp", self.op, self.owner._structural_key())

    def _evaluate(self, ctx) -> pd.DataFrame:
        from .plan import compile_plan
        result = compile_plan([self], ctx)
        if result is None:
            raise TypeError("scope expression is not representable by the Rust matrix plan")
        return result[0]


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

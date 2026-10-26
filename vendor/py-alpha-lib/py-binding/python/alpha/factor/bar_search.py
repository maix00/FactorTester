"""Bar-search operators for the public factor API (Rust execution)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .core import FactorExpr, _to_expr
from .scope import BarCountScope


class BarSinceExpr(FactorExpr):
    def __init__(self, condition: FactorExpr, scope: BarCountScope, *,
                 select: str = "nearest", default: float | None = None,
                 include_current: bool = True):
        self.condition = condition
        self.scope = scope
        self.select = select
        self.default = default
        self.include_current = include_current

    def _structural_key(self):
        return ("alpha.factor.BarSinceExpr", self.scope.count, self.select,
                self.include_current, self.default,
                self.condition._structural_key())

    def _evaluate(self, ctx) -> pd.DataFrame:
        frame = self.condition.evaluate(ctx)
        from alpha import bar_since
        output = {}
        for product in frame.columns:
            values = frame[product].to_numpy(dtype=float)
            output[product] = bar_since(
                values, self.scope.count, self.include_current,
                self.select == "nearest", self.default is None,
                0.0 if self.default is None else float(self.default),
            )
        return pd.DataFrame(output, index=frame.index)


def bar_since(condition, *, scope: BarCountScope, select: str = "nearest",
              default: float | None = None, include_current: bool = True) -> BarSinceExpr:
    return BarSinceExpr(
        _to_expr(condition), scope, select=select, default=default,
        include_current=include_current,
    )

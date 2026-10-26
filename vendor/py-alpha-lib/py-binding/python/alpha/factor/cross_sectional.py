"""Cross-sectional operators for the public factor API (Rust execution)."""

from __future__ import annotations

import pandas as pd

from .core import FactorExpr, _to_expr


class CrossSectionalExpr(FactorExpr):
    def __init__(self, op: str, operand: FactorExpr):
        self.op = op
        self.operand = operand

    def _structural_key(self):
        return ("alpha.factor.CrossSectionalExpr", self.op, self.operand._structural_key())

    def _evaluate(self, ctx) -> pd.DataFrame:
        frame = self.operand.evaluate(ctx)
        from alpha import cross_sectional
        outputs = cross_sectional(
            [frame[product].to_numpy(dtype=float) for product in frame.columns],
            self.op,
        )
        return pd.DataFrame(
            dict(zip(frame.columns, outputs, strict=True)), index=frame.index,
        )


def _extend_core() -> None:
    def cs_zscore(self):
        return CrossSectionalExpr("cs_zscore", self)

    def cs_rank(self):
        return CrossSectionalExpr("cs_rank", self)

    FactorExpr.cs_zscore = cs_zscore
    FactorExpr.cs_rank = cs_rank


_extend_core()

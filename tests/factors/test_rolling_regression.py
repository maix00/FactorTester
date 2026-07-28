from __future__ import annotations

import pandas as pd
import pytest

from tools.data.types import DataFreq
from tools.factors.expr import EvaluateContext, FactorExpr


class _FrameExpr(FactorExpr):
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def _evaluate(self, ctx):
        return self.frame

    def _structural_key(self):
        return ("RollingRegressionFrame",)

    def _get_alias(self):
        return "FRAME"

    def _to_latex(self, subst=None):
        return "F_t"


def _evaluate(expr: FactorExpr) -> pd.DataFrame:
    return expr.evaluate(
        ctx=EvaluateContext(products=["A"], freq=DataFreq.MIN1, cache={})
    )


def test_rolling_linear_regression_metrics_share_one_ols_definition():
    values = _FrameExpr(pd.DataFrame({"A": [1.0, 2.0, 4.0, 5.0]}))

    slope = _evaluate(values.rolling_linreg_slope(4))
    r2 = _evaluate(values.rolling_linreg_r2(4))
    tstat = _evaluate(values.rolling_linreg_tstat(4))
    resid_std = _evaluate(values.rolling_linreg_resid_std(4))

    assert slope.iloc[-1, 0] == pytest.approx(1.4)
    assert r2.iloc[-1, 0] == pytest.approx(0.98)
    assert tstat.iloc[-1, 0] == pytest.approx(9.899494936611665)
    assert resid_std.iloc[-1, 0] == pytest.approx(0.31622776601683794)


def test_rolling_linear_regression_requires_three_finite_observations():
    values = _FrameExpr(
        pd.DataFrame({"A": [1.0, float("nan"), 3.0, float("nan")]})
    )

    for expr in (
        values.rolling_linreg_slope(4),
        values.rolling_linreg_r2(4),
        values.rolling_linreg_tstat(4),
        values.rolling_linreg_resid_std(4),
    ):
        assert pd.isna(_evaluate(expr).iloc[-1, 0])


def test_rolling_linear_regression_preserves_missing_bar_positions():
    values = _FrameExpr(
        pd.DataFrame({"A": [1.0, float("nan"), 3.0, 5.0]})
    )

    assert _evaluate(
        values.rolling_linreg_slope(4)
    ).iloc[-1, 0] == pytest.approx(9 / 7)
    assert _evaluate(
        values.rolling_linreg_resid_std(4)
    ).iloc[-1, 0] == pytest.approx(0.5345224838248488)

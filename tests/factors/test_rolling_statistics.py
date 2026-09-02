from __future__ import annotations

import pandas as pd
import pytest

from tools.data.types import DataFreq
from tools.data.types import DataColumn
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef
from tools.factors.expr import (
    EvaluateContext,
    FactorExpr,
    build_panel_timeline,
)
from tools.parameters import TypeParam


class _FrameExpr(FactorExpr):
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def _evaluate(self, ctx):
        return self.frame

    def _structural_key(self):
        return ("RollingStatisticsFrame",)

    def _get_alias(self):
        return "FRAME"

    def _to_latex(self, subst=None):
        return "F_t"


class _ParameterizedQuantileFamily(FactorFamily):
    @staticmethod
    def factor_expr():
        probability = TypeParam("M", default_value=0.9, typ=(int, float))
        return ColumnRef(DataColumn.CLOSE).rolling_quantile(probability, 3)


def _evaluate(expr: FactorExpr) -> pd.DataFrame:
    return expr.evaluate(
        ctx=EvaluateContext(products=["A"], freq=DataFreq.MIN1, cache={})
    )


def test_robust_rolling_statistics_use_the_current_window():
    values = _FrameExpr(pd.DataFrame({"A": [1.0, 100.0, 3.0, 4.0]}))

    median = _evaluate(values.rolling_median(3))
    quantile = _evaluate(values.rolling_quantile(0.25, 3))
    mad = _evaluate(values.rolling_mad(3))

    assert median.iloc[-1, 0] == 4.0
    assert quantile.iloc[-1, 0] == 3.5
    assert mad.iloc[-1, 0] == 1.0


def test_rolling_quantile_rejects_out_of_range_probability():
    values = _FrameExpr(pd.DataFrame({"A": [1.0, 2.0]}))

    with pytest.raises(ValueError, match="between 0 and 1"):
        values.rolling_quantile(1.1, 2)


def test_rolling_quantile_accepts_scalar_parameter_after_resolution():
    values = _FrameExpr(pd.DataFrame({"A": [1.0, 2.0, 3.0, 4.0]}))
    probability = TypeParam("M", default_value=0.9, typ=(int, float))
    expression = values.rolling_quantile(probability, 3)

    assert "M" in expression.to_latex()

    resolved = expression.resolve(param_values={"M": 0.5})
    assert _evaluate(resolved).iloc[-1, 0] == 3.0


def test_factor_family_builds_formula_before_quantile_parameter_resolution():
    family = _ParameterizedQuantileFamily()

    assert "M" in family.math_expr
    assert "M:0.5" in family.get_factor(M=0.5).alias


def test_robust_rolling_statistics_ignore_missing_observations():
    values = _FrameExpr(
        pd.DataFrame({"A": [1.0, float("nan"), 3.0, 5.0]})
    )

    assert _evaluate(values.rolling_median(4)).iloc[-1, 0] == 3.0
    assert _evaluate(values.rolling_quantile(0.25, 4)).iloc[-1, 0] == 2.0
    assert _evaluate(values.rolling_mad(4)).iloc[-1, 0] == 2.0


def test_fluent_rolling_builder_exposes_new_statistics():
    values = _FrameExpr(pd.DataFrame({"A": [1.0, 2.0, 4.0, 5.0]}))

    pairs = (
        (values.rolling(4).median(), values.rolling_median(4)),
        (values.rolling(4).quantile(0.25), values.rolling_quantile(0.25, 4)),
        (values.rolling(4).mad(), values.rolling_mad(4)),
        (values.rolling(4).linreg_slope(), values.rolling_linreg_slope(4)),
        (values.rolling(4).linreg_r2(), values.rolling_linreg_r2(4)),
        (values.rolling(4).linreg_tstat(), values.rolling_linreg_tstat(4)),
        (
            values.rolling(4).linreg_resid_std(),
            values.rolling_linreg_resid_std(4),
        ),
    )

    for fluent, direct in pairs:
        pd.testing.assert_frame_equal(_evaluate(fluent), _evaluate(direct))
        assert fluent._structural_key() == direct._structural_key()


def test_new_rolling_statistics_compact_asynchronous_product_sessions():
    index = pd.to_datetime([
        "2025-01-01 09:00",
        "2025-01-01 09:01",
        "2025-01-01 09:02",
    ])
    values = _FrameExpr(pd.DataFrame(
        {"A": [1.0, float("nan"), 3.0], "B": [10.0, 20.0, 30.0]},
        index=index,
    ))
    preloaded = {
        ("A", "MIN1"): pd.DataFrame(
            {"CLOSE": [1.0, 3.0]}, index=index[[0, 2]],
        ),
        ("B", "MIN1"): pd.DataFrame(
            {"CLOSE": [10.0, 20.0, 30.0]}, index=index,
        ),
    }
    context = EvaluateContext(
        products=["A", "B"],
        freq=DataFreq.MIN1,
        cache={},
        panel_timeline=build_panel_timeline(
            ["A", "B"], DataFreq.MIN1, preloaded,
        ),
    )

    median = values.rolling_median(2).evaluate(ctx=context)
    quantile = values.rolling_quantile(0.5, 2).evaluate(ctx=context)
    slope = values.rolling_linreg_slope(3).evaluate(ctx=context)

    assert median.loc[index[2], "A"] == 2.0
    assert median.loc[index[2], "B"] == 25.0
    pd.testing.assert_frame_equal(median, quantile)
    assert pd.isna(slope.loc[index[2], "A"])
    assert slope.loc[index[2], "B"] == pytest.approx(10.0)

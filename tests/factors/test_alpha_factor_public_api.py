import numpy as np
import pandas as pd

from alpha.factor import (
    ColumnRef,
    EvalContext,
    FactorExpr,
    Parameter,
    TypeParam,
    ParamRef,
    _to_expr,
)


def _ctx(values):
    return EvalContext(
        products=('A',),
        preloaded={'A': pd.DataFrame({'CLOSE': values})},
    )


def test_alpha_factor_public_api_evaluates_without_factortester_objects():
    values = np.arange(20, dtype=float)
    expression = ColumnRef('CLOSE').rolling(3).mean()
    result = expression.evaluate(_ctx(values))
    expected = pd.Series(values).rolling(3, min_periods=1).mean().to_numpy()
    np.testing.assert_allclose(result['A'].to_numpy(), expected)


def test_alpha_factor_public_api_supports_parameters_and_composition():
    parameter = TypeParam('N', default_value=3, typ=int)
    resolved = ParamRef(parameter).resolve()
    assert resolved.value == 3
    expression = (ColumnRef('CLOSE').rolling(3).mean() + 1.0).shift(1)
    result = expression.evaluate(_ctx(np.arange(10, dtype=float)))
    assert np.isnan(result['A'].iloc[0])
    assert result['A'].iloc[1] == 1.0

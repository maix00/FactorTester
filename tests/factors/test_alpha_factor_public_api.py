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


def test_alpha_factor_window_semantics():
    from alpha.factor import NanPolicy

    values = np.array([1.0, np.nan, 3.0, 4.0])
    ctx = _ctx(values)
    default = ColumnRef('CLOSE').rolling(2).mean().evaluate(ctx)['A'].to_numpy()
    skip = (
        ColumnRef('CLOSE').rolling(2)
        .semantics(min_periods=1, nan_policy=NanPolicy.SKIP)
        .mean()
        .evaluate(ctx)['A'].to_numpy()
    )
    np.testing.assert_allclose(default, [1.0, np.nan, np.nan, 3.5], equal_nan=True)
    np.testing.assert_allclose(skip, [1.0, 1.0, 3.0, 3.5])


def test_alpha_factor_cross_sectional_executes_in_rust():
    frame_a = pd.DataFrame({'CLOSE': [1.0, 2.0, 3.0]})
    frame_b = pd.DataFrame({'CLOSE': [3.0, 2.0, 1.0]})
    ctx = EvalContext(products=('A', 'B'), preloaded={'A': frame_a, 'B': frame_b})
    result = ColumnRef('CLOSE').cs_zscore().evaluate(ctx)
    np.testing.assert_allclose(result['A'].to_numpy(), [-1.0, 0.0, 1.0])
    np.testing.assert_allclose(result['B'].to_numpy(), [1.0, 0.0, -1.0])


def test_alpha_factor_family_owns_versioned_identity():
    from alpha.factor import FactorFamily

    class Momentum(FactorFamily):
        alias = 'momentum'

        @staticmethod
        def factor_expr():
            return ColumnRef('CLOSE').rolling(3).mean()

    definition = Momentum.get_factor(owner_ref='tester')
    assert definition.ref.startswith('factor:v2:')
    assert definition.identity.factor_ref == definition.ref
    assert definition.identity.family_ref.startswith('factor-family:v2:')
    first = definition
    second = Momentum.get_factor(owner_ref='tester')
    assert first.ref == second.ref
    other = Momentum.get_factor(owner_ref='other')
    assert other.ref != first.ref

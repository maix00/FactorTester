"""Rendering must preserve operator grouping without changing expression identity."""
import pytest
from tools.factors.expr import OPEN, CLOSE, HIGH, window_bars
from tools.factors.Parameters import FactorFreqParam
from tools.factors.expr.leaf import ConstExpr


def test_shift_subtracts_the_entire_composite_window():
    window = window_bars(FactorFreqParam) - 1
    assert OPEN.shift(window).to_latex() == (
        r'\tilde{O}_{t - \left(\mathrm{Bars}\left(\textcolor{red}{\$F}\right) - 1\right)}'
    )


@pytest.mark.parametrize('period', [OPEN + CLOSE, OPEN - CLOSE, OPEN < CLOSE])
def test_shift_composite_offset_is_grouped(period):
    assert OPEN.shift(period)._to_latex().endswith(
        r'\left(' + period._to_latex() + r'\right)}'
    )


def test_shift_negative_and_atomic_offsets():
    assert OPEN.shift(-2).to_latex() == r'\tilde{O}_{t - \left(-2\right)}'
    assert OPEN.shift(2).to_latex() == r'\tilde{O}_{t - 2}'
    assert OPEN.shift(FactorFreqParam).to_latex() == r'\tilde{O}_{t - \textcolor{red}{\$F}}'


@pytest.mark.parametrize('operand', [OPEN + CLOSE, OPEN - CLOSE, OPEN * CLOSE, OPEN.shift(2), OPEN.rolling(5).mean()])
def test_shift_applies_to_the_entire_expression(operand):
    assert operand.shift(3)._to_latex() == (
        r'\operatorname{Shift}_{3}\left(' + operand._to_latex() + r'\right)'
    )
    assert operand.shift(0)._to_latex() == operand._to_latex()


def test_shift_named_intermediate_and_offset_substitutions():
    operand = OPEN + CLOSE
    period = window_bars(FactorFreqParam) - 1
    assert operand.shift(period)._to_latex({operand._structural_key(): 'A',period._structural_key(): 'B'}) == 'A_{t - B_t}'


@pytest.mark.parametrize('power', [12, -2, OPEN + CLOSE, OPEN ** CLOSE])
def test_power_exponent_is_one_tex_group(power):
    expr = CLOSE ** power
    assert expr._to_latex() == CLOSE._to_latex() + '^{' + expr.operands[1]._to_latex() + '}'


@pytest.mark.parametrize('base', [-OPEN, ConstExpr(-2), OPEN + CLOSE, OPEN ** CLOSE])
def test_power_base_keeps_grouping(base):
    assert (base ** HIGH)._to_latex() == r'\left(' + base._to_latex() + r'\right)^{' + HIGH._to_latex() + '}'


def test_sqrt_covers_the_whole_radicand():
    assert (OPEN + CLOSE).sqrt()._to_latex() == r'\sqrt{' + (OPEN + CLOSE)._to_latex() + '}'


def test_existing_binary_function_and_window_grouping():
    rhs = CLOSE - HIGH
    assert (OPEN - rhs)._to_latex() == OPEN._to_latex() + r' - \left(' + rhs._to_latex() + r'\right)'
    assert (OPEN / (CLOSE + HIGH))._to_latex() == r'\frac{' + OPEN._to_latex() + '}{' + (CLOSE + HIGH)._to_latex() + '}'
    assert (OPEN + CLOSE).rolling(5).mean()._to_latex().endswith(r'\left(' + (OPEN + CLOSE)._to_latex() + r'\right)')


def test_rendering_is_pure_for_identity_and_parameters():
    expr = (OPEN ** 12).shift(window_bars(FactorFreqParam) - 1)
    before = (expr._structural_key(), expr._get_alias(), FactorFreqParam.alias)
    expr.to_latex()
    assert before == (expr._structural_key(), expr._get_alias(), FactorFreqParam.alias)


def test_groupby_scope_uses_the_same_symbol_with_a_superscript():
    """与 rolling 同字面 R：rolling 用下标承载窗口，groupby_scope 用上标承载作用域。"""
    import pandas as pd

    from tools.factors.expr.core import FactorExpr
    from tools.factors.expr.groupby_scope import GroupByScopeExpr
    from tools.factors.expr.lookback_scope import scope_bars, scope_session, scope_trading_day

    class _Frame(FactorExpr):
        def _evaluate(self, ctx):
            return pd.DataFrame({"A": [1.0]})

        def _structural_key(self):
            return ("latex-frame", id(self))

        def _to_latex(self, subst=None):
            return "X"

        def _get_alias(self):
            return "X"

    data = _Frame()

    assert GroupByScopeExpr(scope_trading_day(), data).mean()._to_latex() == \
        r"\mathrm{R}^{\text{trading\_day}}"
    assert GroupByScopeExpr(scope_bars(5), data).mean()._to_latex() == \
        r"\mathrm{R}^{\text{bars}(K)}"
    assert GroupByScopeExpr(scope_session(gap="3h"), data).mean()._to_latex() == \
        r"\mathrm{R}^{\text{session}(3h)}"
    # 截断写进上标，与 rolling 的下标写法对称
    truncated = GroupByScopeExpr(scope_trading_day(), data).truncate(0, 119).mean()._to_latex()
    assert truncated.startswith(r"\mathrm{R}^{\text{trading\_day},\mathrm{trunc}(")
    assert truncated.endswith(")}")
    # rolling 仍是下标、不带上标（两者只靠上/下标区分作用域与窗口）
    rolling_latex = data.rolling(20).mean()._to_latex()
    assert "_{20}" in rolling_latex, rolling_latex
    assert "^{" not in rolling_latex, rolling_latex

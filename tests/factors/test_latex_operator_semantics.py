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

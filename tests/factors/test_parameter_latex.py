"""Symbolic parameters must remain literal inside generated math."""
import re

from tools.factors.Parameters import FactorFreqParam
from tools.factors.expr.leaf import ColumnRef, ParamRef
from tools.factors.expr.signal_align import SignalAlign
from tools.factors.expr.term_structure import TermStructureOp
from tools.data.types import DataColumn


def test_frequency_parameter_in_shift_is_escaped_everywhere():
    expr = ColumnRef(DataColumn.OPEN_ADJUSTED).shift(FactorFreqParam)
    latex = SignalAlign(expr, '$F').to_latex()
    assert latex.count(r'\textcolor{red}{\$F}') == 2
    assert not re.search(r'(?<!\\)\$', latex)
    assert FactorFreqParam.alias == '$F'


def test_term_structure_column_parameter_uses_same_literal_label():
    expr = ParamRef(FactorFreqParam)
    assert TermStructureOp._operand_latex_arg(expr, column=True) == r'\textcolor{red}{\$F}'

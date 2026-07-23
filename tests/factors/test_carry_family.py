from __future__ import annotations

from server.services.factor_registry import get_factor_family_instance
from tools.data.types import DataColumn
from tools.factors.expr import ParamRef, TermStructureOp


def test_public_carry_family_has_term_structure_signal_semantics():
    family = get_factor_family_instance("$COMMON:Carry", username="tester")

    expr = family._expr
    assert isinstance(expr, TermStructureOp)
    assert expr.op == "term_carry_annualized"
    assert expr.operands[0].value == 0
    assert expr.operands[1].value == 1
    assert isinstance(expr.operands[2], ParamRef)
    assert expr.operands[2].param.default_value == DataColumn.CLOSE


def test_carry_alias_keeps_price_and_signal_frequency_parameters():
    family = get_factor_family_instance("$COMMON:Carry", username="tester")

    factor = family.get_factor(**{"P": "C", "$F": "1d"})

    assert factor.alias == "Carry|P:C|$F:1d"

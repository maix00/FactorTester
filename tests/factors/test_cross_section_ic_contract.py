from __future__ import annotations

from typing import Any

from tools.factors.FactorExpr import CrossSectionalOp, ShiftOp
from tools.factors.tests.CrossSectionIC import CrossSectionIC
from tools.factors.tests.NextReturns import NextReturns


def _walk(node: Any):
    stack = [node]
    seen = set()
    while stack:
        cur = stack.pop()
        sk = getattr(cur, "_structural_key", lambda: id(cur))()
        if sk in seen:
            continue
        seen.add(sk)
        yield cur
        for child in getattr(cur, "operands", ()) or getattr(cur, "_operands", ()):
            stack.append(child)


def test_cross_section_ic_expr_marks_fe_and_re_as_intermediate():
    expr = CrossSectionIC.factor_expr()
    names = {getattr(n, "_intermediate_name", None) for n in _walk(expr) if getattr(n, "_is_intermediate", False)}
    assert "FE" in names
    assert "RE" in names


def test_next_returns_expr_is_double_shift_expression():
    expr = NextReturns.factor_expr()
    assert isinstance(expr, ShiftOp)
    assert isinstance(expr.operand, ShiftOp)


def test_cross_section_ic_re_is_factor_param_intermediate():
    expr = CrossSectionIC.factor_expr()
    re_nodes = [n for n in _walk(expr) if getattr(n, "_is_intermediate", False) and getattr(n, "_intermediate_name", None) == "RE"]
    assert len(re_nodes) == 1
    assert not isinstance(re_nodes[0], ShiftOp)


def test_cross_section_ic_outer_is_cs_spearman_against_shifted_re():
    expr = CrossSectionIC.factor_expr()
    # outer: FE.cs_spearman(RE.shift(-Lag))
    assert isinstance(expr, CrossSectionalOp)
    assert expr.op == "cs_spearman"

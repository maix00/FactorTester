from __future__ import annotations

import pytest

from tools.data.types.DataColumn import DataColumn
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef, CompositeExpr


def test_neg_intermediate_structural_key_differs_from_plain():
    base = ColumnRef(DataColumn.CLOSE)
    plain = base.as_intermediate("X")
    negd = (-base).as_intermediate("X")
    assert plain._structural_key() != negd._structural_key()


def test_collect_intermediate_aliases_rejects_same_name_for_different_exprs():
    class FF(FactorFamily):
        @staticmethod
        def factor_expr():
            base = ColumnRef(DataColumn.CLOSE)
            a = base.as_intermediate("X")
            b = (-base).as_intermediate("X")
            return CompositeExpr("add", a, b)

    # construction triggers LaTeX generation, which must reject name collisions
    with pytest.raises(ValueError, match="Intermediate 名称冲突"):
        FF()

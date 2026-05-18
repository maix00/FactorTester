from __future__ import annotations

import pandas as pd

from tools.data.DataColumn import DataColumn
from tools.factors.FactorExpr import ColumnRef
from tools.factors.FactorRunResult import FactorRunResult


class _FakeFactor:
    def __init__(self, neg: bool):
        source = ColumnRef(DataColumn.CLOSE)
        self._func_expr = -source if neg else source


def test_func_table_is_derived_from_source_table_for_reversed_factor():
    result = FactorRunResult(_FakeFactor(neg=True))
    result.source_table = pd.DataFrame({"A": [1.0, -2.0]})

    pd.testing.assert_frame_equal(result.func_table, pd.DataFrame({"A": [-1.0, 2.0]}))


def test_source_table_is_derived_from_func_table_for_reversed_factor():
    result = FactorRunResult(_FakeFactor(neg=True))
    result.func_table = pd.DataFrame({"A": [-1.0, 2.0]})

    pd.testing.assert_frame_equal(result.source_table, pd.DataFrame({"A": [1.0, -2.0]}))

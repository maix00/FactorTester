from __future__ import annotations

from tools.factors.FactorFamily import FactorFamily


class NextReturns(FactorFamily):
    """Test-scoped next-period returns expression family."""

    @staticmethod
    def factor_expr():
        from tools.data.types import DataColumn
        from tools.parameters import DataColumnParam, WindowParam, TypeParam

        SC = DataColumnParam('SC', default_value=DataColumn.CLOSE_ADJUSTED)
        RF = WindowParam('RF')
        S = TypeParam('S', default_value=1, typ=int)
        return (SC.delta(RF) / SC.shift(RF)).shift(-RF).shift(S - 1)

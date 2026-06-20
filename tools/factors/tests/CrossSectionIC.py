from __future__ import annotations

from tools.factors.FactorFamily import FactorFamily


class CrossSectionIC(FactorFamily):
    """Test-scoped cross-sectional IC family driven by an explicit returns factor."""

    @staticmethod
    def factor_expr():
        from tools.parameters import FactorParam, TypeParam

        FE = FactorParam('FE')
        RE = FactorParam('RE')
        Lag = TypeParam('Lag', default_value=0, typ=int)

        FE = FE.as_intermediate('FE')
        RE = RE.as_intermediate('RE')

        return FE.cs_spearman(RE.shift(-Lag))

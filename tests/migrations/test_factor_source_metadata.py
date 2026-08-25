from __future__ import annotations

from server.modules.custom_factors.catalog import _load_factor_family_from_source
from tools.migrations.migrate_factor_source_metadata import (
    _upgrade_legacy_formula_source,
)


LEGACY_VLYZ_SOURCE = """
from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam
from tools.factors.FactorExpr import FactorExpr

class VlYZ(FactorFamily):
    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='14d')
        C = DataColumnParam('C', default_value='CA')
        sig_o2 = C.shift(0).rolling_var(N)
        sig_c2 = C.shift(0).rolling_var(N)
        sig_rs2 = C.shift(0).rolling_var(N)
        yz_var = (sig_o2 + _DynamicWeight(N) * sig_c2 + (1.0 - _DynamicWeight(N)) * sig_rs2).as_intermediate('SIG_YZ2')
        return yz_var.max(0.0).sqrt()

class _DynamicWeight(FactorExpr):
    pass

if __name__ == '__main__':
    VlYZ()
""".lstrip()


def test_legacy_vlyz_source_is_upgraded_to_structurally_identified_formula() -> None:
    upgraded = _upgrade_legacy_formula_source("VlYZ", LEGACY_VLYZ_SOURCE)

    assert "_DynamicWeight" not in upgraded
    assert "window_bars(N)" in upgraded
    family_type, module = _load_factor_family_from_source(upgraded, "test_vlyz")
    assert family_type is not None
    assert module is not None
    assert len(family_type().expr.semantic_fingerprint()) == 64


def test_unrelated_factor_source_is_not_rewritten() -> None:
    source = "class Momentum: pass\n"

    assert _upgrade_legacy_formula_source("Momentum", source) == source

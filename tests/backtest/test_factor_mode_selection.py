from __future__ import annotations

from tools.testers.backtest.engines.factors import FactorMode, select_factor_mode
from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef


def test_auto_prefers_precomputed_for_vectorizable_expression() -> None:
    expression = ColumnRef(DataColumn.CLOSE) + 1.0

    assert select_factor_mode("auto", expression, ("A",)) == FactorMode.PRECOMPUTED


def test_auto_selects_incremental_for_live_only_expression() -> None:
    class LiveOnlyExpr(ColumnRef):
        def supports_vectorized(self) -> bool:
            return False

    expression = LiveOnlyExpr(DataColumn.CLOSE) + 1.0

    assert select_factor_mode("auto", expression, ("A",)) == FactorMode.INCREMENTAL


def test_explicit_incremental_selects_supported_rolling_ema() -> None:
    expression = ColumnRef(DataColumn.CLOSE).rolling_ema(3)

    assert select_factor_mode("incremental", expression, ("A",)) == FactorMode.INCREMENTAL

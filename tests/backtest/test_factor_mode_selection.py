from __future__ import annotations

import pytest

from tools.testers.backtest.engines.factors import FactorMode, select_factor_mode
from tools.testers.backtest.engines.factors.incremental import UnsupportedStreamingFactor
from tools.data.types import DataColumn
from tools.factors.expr import ColumnRef


def test_auto_selects_incremental_for_supported_expression() -> None:
    expression = ColumnRef(DataColumn.CLOSE) + 1.0

    assert select_factor_mode("auto", expression, ("A",)) == FactorMode.INCREMENTAL


def test_auto_selects_precomputed_for_unsupported_streaming_expression() -> None:
    expression = ColumnRef(DataColumn.CLOSE).rolling_ema(3)

    assert select_factor_mode("auto", expression, ("A",)) == FactorMode.PRECOMPUTED


def test_explicit_incremental_never_falls_back_to_precomputed() -> None:
    expression = ColumnRef(DataColumn.CLOSE).rolling_ema(3)

    with pytest.raises(UnsupportedStreamingFactor):
        select_factor_mode("incremental", expression, ("A",))

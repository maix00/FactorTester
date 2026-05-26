from __future__ import annotations

import pandas as pd

from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef
from tools.parameters import WindowParam


class _Meta:
    def __init__(self, data: pd.DataFrame, day_periods: int):
        self.data = data
        self.day_periods = day_periods

    def get_and_adjust_cols(self, columns, copy=False, start_calc_point=None):
        return self.data[columns]


class _Product:
    name = "SOURCE_FREQ_PRODUCT"

    def __init__(self):
        minute_index = pd.date_range("2026-01-02 09:01", periods=4, freq="min", name="MIN1")
        day_index = pd.DatetimeIndex(["2026-01-02", "2026-01-05"], name="DAY1")
        self.MIN1 = _Meta(pd.DataFrame({"CLOSE": [1.0, 2.0, 3.0, 4.0]}, index=minute_index), day_periods=2)
        self.DAY1 = _Meta(pd.DataFrame({"CLOSE": [1.0, 4.0]}, index=day_index), day_periods=1)

    def list_available_freqs(self):
        return [DataFreq.MIN1, DataFreq.DAY1]


class _DailyWindowMinuteSignal(FactorFamily):
    @staticmethod
    def factor_expr():
        window = WindowParam("SourceFrequencyWindow", default_value="1D")
        return ColumnRef(DataColumn.CLOSE).rolling(window).min()


def test_source_frequency_is_fine_enough_for_signal_alignment():
    factor = _DailyWindowMinuteSignal().get_factor(
        SourceFrequencyWindow="1D",
        **{"$F": "1m", "$Rev": "0"},
    )

    result = factor.evaluate([_Product()])

    assert factor._source_freq == DataFreq.MIN1
    assert not result.empty

from __future__ import annotations

import pandas as pd
from types import SimpleNamespace

from tools.data.types import DataColumn
from tools.data.types import DataFreq
from tools.data.types import DataTime
from tools.factors import FactorFamily
from tools.factors.FactorExpr import ColumnRef
from tools.parameters import WindowParam


class _Meta:
    def __init__(self, data: pd.DataFrame, day_periods: int):
        self.data = data
        self.day_periods = day_periods

    def get_and_adjust_cols(self, columns, copy=False, start_dt=None, end_dt=None, warmup_window=None):
        return self.data[columns]


class _WindowAwareMeta(_Meta):
    """Small ProductDataView stand-in that honours the requested run window."""

    def get_and_adjust_cols(self, columns, copy=False, start_dt=None, end_dt=None, warmup_window=None):
        frame = self.data[columns]
        event_times = pd.DatetimeIndex(frame.index.get_level_values(-1))
        if start_dt is not None:
            start = pd.Timestamp(start_dt.ts).tz_localize(None)
            frame = frame[event_times >= start]
            event_times = event_times[event_times >= start]
        if end_dt is not None:
            end = pd.Timestamp(end_dt.ts).tz_localize(None)
            frame = frame[event_times <= end]
        return frame


class _Product:
    name = "SOURCE_FREQ_PRODUCT"

    def __init__(self):
        minute_times = pd.DatetimeIndex(
            list(pd.date_range("2026-01-02 09:01", periods=4, freq="min"))
            + list(pd.date_range("2026-01-05 09:01", periods=4, freq="min")),
            name="MIN1",
        )
        minute_index = pd.MultiIndex.from_arrays(
            [minute_times.normalize(), minute_times],
            names=["DAY1", "MIN1"],
        )
        day_index = pd.DatetimeIndex(["2026-01-02", "2026-01-05"], name="DAY1")
        self.MIN1 = _Meta(
            pd.DataFrame({"CLOSE": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]}, index=minute_index),
            day_periods=2,
        )
        self.DAY1 = _Meta(pd.DataFrame({"CLOSE": [1.0, 4.0]}, index=day_index), day_periods=1)

    def list_available_freqs(self):
        return [DataFreq.MIN1, DataFreq.DAY1]


class _DailyWindowMinuteSignal(FactorFamily):
    @staticmethod
    def factor_expr():
        window = WindowParam("SourceFrequencyWindow", default_value="1D")
        return ColumnRef(DataColumn.CLOSE).rolling(window).min()


class _DeclaredMinuteSourceDailySignal(_DailyWindowMinuteSignal):
    source_freq = "1m"


class _ConstantMinuteSignal(FactorFamily):
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        close = ColumnRef(DataColumn.CLOSE)
        return close - close


class _WindowAwareConstantMinuteSignal(FactorFamily):
    source_freq = "1m"

    @staticmethod
    def factor_expr():
        close = ColumnRef(DataColumn.CLOSE)
        return close - close


class _WindowAwareProduct(_Product):
    name = "WINDOW_AWARE_PRODUCT"

    def __init__(self):
        super().__init__()
        self.MIN1 = _WindowAwareMeta(self.MIN1.data, day_periods=2)


class _DailyOnlyProduct(_Product):
    name = "DAILY_ONLY_PRODUCT"

    def list_available_freqs(self):
        return [DataFreq.DAY1]


class _PreviousReloadProduct(_Product):
    def list_available_freqs(self):
        return [
            SimpleNamespace(name="MIN1", value=pd.Timedelta("1min")),
            SimpleNamespace(name="DAY1", value=pd.Timedelta("1D")),
        ]


def _window():
    return (
        DataTime.from_dict({"date": "2026-01-02", "time": "09:00", "tz": "Asia/Shanghai"}, precision="exact"),
        DataTime.from_dict({"date": "2026-01-05", "time": "15:00", "tz": "Asia/Shanghai"}, precision="exact"),
    )


def test_source_frequency_is_fine_enough_for_signal_alignment():
    factor = _DailyWindowMinuteSignal().get_factor(
        SourceFrequencyWindow="1D",
        **{"$F": "1m", "$Rev": "0"},
    )

    start_dt, end_dt = _window()
    result = factor.evaluate([_Product()], start_dt=start_dt, end_dt=end_dt)

    assert factor._source_freq == DataFreq.MIN1
    assert not result.empty


def test_declared_source_frequency_overrides_daily_window_and_signal():
    factor = _DeclaredMinuteSourceDailySignal().get_factor(
        SourceFrequencyWindow="1D",
        **{"$F": "1D", "$Rev": "0"},
    )

    start_dt, end_dt = _window()
    factor.evaluate([_Product()], start_dt=start_dt, end_dt=end_dt)

    assert factor._source_freq == DataFreq.MIN1


def test_explicit_source_frequency_normalizes_string_input():
    factor = _DeclaredMinuteSourceDailySignal().get_factor(
        SourceFrequencyWindow="1D",
        **{"$F": "1D", "$Rev": "0"},
    )

    start_dt, end_dt = _window()
    result = factor.evaluate([_Product()], freq="MIN1", start_dt=start_dt, end_dt=end_dt)

    assert factor._source_freq is DataFreq.MIN1
    assert not result.empty


def test_explicit_source_frequency_accepts_product_frequency_from_previous_reload():
    factor = _DeclaredMinuteSourceDailySignal().get_factor(
        SourceFrequencyWindow="1D",
        **{"$F": "1D", "$Rev": "0"},
    )

    start_dt, end_dt = _window()
    result = factor.evaluate([_PreviousReloadProduct()], freq="MIN1", start_dt=start_dt, end_dt=end_dt)

    assert not result.empty


def test_declared_source_frequency_skips_products_without_that_source():
    factor = _DeclaredMinuteSourceDailySignal().get_factor(
        SourceFrequencyWindow="1D",
        **{"$F": "1D", "$Rev": "0"},
    )
    minute_product = _Product()
    factor.clear()

    start_dt, end_dt = _window()
    result = factor.evaluate([minute_product, _DailyOnlyProduct()], start_dt=start_dt, end_dt=end_dt)

    assert list(result.columns) == [minute_product]


def test_constant_factor_values_are_retained_for_visualization_and_ic():
    product = _Product()
    factor = _ConstantMinuteSignal().get_factor(**{"$F": "1m", "$Rev": "0"})

    start_dt, end_dt = _window()
    result = factor.evaluate([product], start_dt=start_dt, end_dt=end_dt)

    assert list(result.columns) == [product]
    assert (result[product] == 0.0).all()


def test_reused_factor_does_not_replay_previous_run_window_cache():
    """An interned Factor must not return an earlier run's shorter table."""
    product = _WindowAwareProduct()
    factor = _WindowAwareConstantMinuteSignal().get_factor(**{"$F": "1m", "$Rev": "0"})
    start_dt, full_end_dt = _window()
    short_end_dt = DataTime.from_dict(
        {"date": "2026-01-02", "time": "09:02", "tz": "Asia/Shanghai"},
        precision="exact",
    )

    full = factor.evaluate([product], start_dt=start_dt, end_dt=full_end_dt)
    short = factor.evaluate([product], start_dt=start_dt, end_dt=short_end_dt)

    assert len(full) > len(short)
    assert short.index.get_level_values(-1).max() <= short_end_dt.ts.tz_localize(None)

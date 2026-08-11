from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from tools.testers.backtest.modules.causal_bar import CausalBar
from tools.testers.backtest.modules.factor_signal import _legacy_live_lookback_bars
from tools.testers.backtest.modules.live_price_buffer import LivePriceTableBuffer


def _bar(timestamp: str, **values: float) -> CausalBar:
    ts = pd.Timestamp(timestamp)
    return CausalBar(ts, ts, values)


def test_buffer_appends_and_keeps_last_duplicate_timestamp() -> None:
    buffer = LivePriceTableBuffer()
    buffer.append((_bar("2024-01-01 09:00", P1=1.0),))
    current = buffer.append((
        _bar("2024-01-01 09:00", P1=3.0),
        _bar("2024-01-01 09:01", P1=2.0),
    ))

    expected = pd.DataFrame(
        {"P1": [3.0, 2.0]},
        index=pd.DatetimeIndex(
            ["2024-01-01 09:00", "2024-01-01 09:01"], dtype="datetime64[us]"
        ),
    )
    pd.testing.assert_frame_equal(current, expected)


def test_buffer_expands_columns_and_previous_snapshot_is_stable() -> None:
    buffer = LivePriceTableBuffer()
    buffer.append((_bar("2024-01-01 09:00", P1=1.0),))
    previous = buffer.frame()
    current = buffer.append((_bar("2024-01-01 09:01", P1=2.0, P2=4.0),))

    assert list(previous.index) == [pd.Timestamp("2024-01-01 09:00")]
    assert list(previous.columns) == ["P1"]
    assert previous.iloc[0, 0] == 1.0
    expected = pd.DataFrame(
        {"P1": [1.0, 2.0], "P2": [float("nan"), 4.0]},
        index=pd.DatetimeIndex(
            ["2024-01-01 09:00", "2024-01-01 09:01"], dtype="datetime64[us]"
        ),
    )
    pd.testing.assert_frame_equal(current, expected)


def test_buffer_uses_compatibility_path_for_timezone_aware_tables() -> None:
    first = pd.Timestamp("2024-01-01 09:00", tz="Asia/Shanghai")
    second = pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai")
    table = pd.DataFrame({"P1": [1.0]}, index=pd.DatetimeIndex([first]))
    buffer = LivePriceTableBuffer(table)

    current = buffer.append((CausalBar(second, second, {"P1": 2.0}),))

    expected = pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.DatetimeIndex([first, second]))
    pd.testing.assert_frame_equal(current, expected)


def test_timezone_buffer_rebuilds_duplicate_index_after_bar_trim() -> None:
    first = pd.Timestamp("2024-01-01 09:00", tz="Asia/Shanghai")
    second = pd.Timestamp("2024-01-01 09:01", tz="Asia/Shanghai")
    third = pd.Timestamp("2024-01-01 09:02", tz="Asia/Shanghai")
    buffer = LivePriceTableBuffer(
        pd.DataFrame({"P1": [1.0, 2.0]}, index=pd.DatetimeIndex([first, second]))
    )

    current = buffer.append(
        (CausalBar(third, third, {"P1": 3.0}),),
        lookback_bars=2,
    )
    corrected = buffer.append(
        (CausalBar(second, second, {"P1": 4.0}),),
        lookback_bars=2,
    )

    assert current["P1"].tolist() == [2.0, 3.0]
    assert corrected["P1"].tolist() == [3.0, 4.0]


def test_buffer_keeps_only_declared_trailing_bar_support() -> None:
    buffer = LivePriceTableBuffer()
    bars = tuple(
        _bar(f"2024-01-01 09:{minute:02d}", P1=float(minute))
        for minute in range(10)
    )
    current = buffer.append(bars, lookback_bars=3)

    assert list(current.index) == list(pd.DatetimeIndex([
        "2024-01-01 09:07",
        "2024-01-01 09:08",
        "2024-01-01 09:09",
    ], dtype="datetime64[ns]"))
    assert current["P1"].tolist() == [7.0, 8.0, 9.0]


def test_duplicate_replay_still_applies_declared_lookback() -> None:
    buffer = LivePriceTableBuffer()
    buffer.append((
        _bar("2024-01-01 09:00", P1=1.0),
        _bar("2024-01-01 09:01", P1=2.0),
    ))
    current = buffer.append((
        _bar("2024-01-01 09:00", P1=3.0),
        _bar("2024-01-01 09:02", P1=4.0),
    ), lookback_bars=2)

    # The corrected 09:00 row is moved after 09:01 by keep="last"; the final
    # two logical bars are therefore the corrected row and 09:02.
    assert current["P1"].tolist() == [3.0, 4.0]


def test_legacy_duration_lookback_is_resolved_to_bars_once() -> None:
    class _DurationFactor:
        live_lookback_window = "2min"

    class _BarFactor:
        live_lookback_bars = 5

    class _AliasFactor:
        required_lookback = "3min"

    assert _legacy_live_lookback_bars(
        _DurationFactor(), source_freq="MIN1", products=()
    ) == 2
    assert _legacy_live_lookback_bars(
        _BarFactor(), source_freq="MIN1", products=()
    ) == 5
    assert _legacy_live_lookback_bars(
        _AliasFactor(), source_freq="MIN1", products=()
    ) == 3


def test_legacy_duration_uses_product_session_bar_count_like_rolling() -> None:
    class _DurationFactor:
        live_lookback_window = "2d"

    product = type(
        "_Product",
        (),
        {"MIN1": SimpleNamespace(day_periods=240)},
    )()

    assert _legacy_live_lookback_bars(
        _DurationFactor(), source_freq="MIN1", products=(product,)
    ) == 480

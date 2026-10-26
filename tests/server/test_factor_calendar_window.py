from tools.factors.expr.streaming.calendar_window import (
    TradingCalendarWindow,
    TradingSession,
)
from tools.factors.expr.streaming.incremental import resolve_trading_day_window


def _calendar():
    return TradingCalendarWindow(tuple(
        TradingSession(day, day * 10_000, day * 10_000 + 9_000,
                       200 if day % 2 else 300)
        for day in range(1, 261)
    ))


def test_250_sessions_have_variable_minute_bar_count():
    window = _calendar()
    assert window.window_size(259, 250) == 125 * 300 + 125 * 200
    assert window.window_size(10, 250) == sum(
        (300 if day % 2 == 0 else 200) for day in range(1, 12)
    )


def test_250d_resolves_to_250_sessions_not_250_bars():
    assert resolve_trading_day_window(
        "250d", calendar_window=_calendar(), current_session=259,
    ) == 125 * 300 + 125 * 200


def test_night_session_is_labelled_by_next_trading_day():
    sessions = (
        TradingSession("2025-02-03", 0, 1_000, 10),
        TradingSession("2025-02-04", 2_000, 3_000, 20),
        TradingSession("2025-02-05", 4_000, 5_000, 30),
    )
    window = TradingCalendarWindow(sessions)
    assert window.window_for_timestamp(2_500, 2) == (1, 30)
    assert window.window_for_timestamp(4_500, 2) == (2, 50)
    assert window.eviction_session(2, 2) == 0


def test_calendar_from_bars_merges_night_and_day_into_one_session():
    from types import SimpleNamespace

    day = "2025-02-04"
    bars = [
        SimpleNamespace(trading_day=day,
                        clock=SimpleNamespace(interval_open_ns=0, interval_end_ns=10)),
        SimpleNamespace(trading_day=day,
                        clock=SimpleNamespace(interval_open_ns=20, interval_end_ns=30)),
        SimpleNamespace(trading_day="2025-02-05",
                        clock=SimpleNamespace(interval_open_ns=40, interval_end_ns=50)),
    ]
    window = TradingCalendarWindow.from_bars(bars)
    assert window.sessions[0].trading_day == day
    assert window.sessions[0].start_ns == 0
    assert window.sessions[0].end_ns == 30
    assert window.sessions[0].bar_count == 2


def test_sub_day_duration_is_fixed_bar_count():
    from tools.factors.expr.streaming.incremental import _resolve_window_bars

    assert _resolve_window_bars("30m", "1m") == 30
    assert _resolve_window_bars("8h", "1m") == 480


def test_multi_day_duration_requires_calendar():
    import pytest
    from tools.factors.expr.streaming.incremental import (
        UnsupportedStreamingFactor,
        _resolve_window_bars,
    )

    with pytest.raises(UnsupportedStreamingFactor):
        _resolve_window_bars("250d", "1m")

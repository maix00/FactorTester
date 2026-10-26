from types import SimpleNamespace

from server.services.nautilus_bridge.nautilus_events import NautilusEventTimeline
from tools.factors.events import EventId


def test_nautilus_bars_record_trading_day_and_session_events():
    sessions = [
        SimpleNamespace(trading_day="2026-01-05", start_ns=0, end_ns=10, bar_count=10),
        SimpleNamespace(trading_day="2026-01-06", start_ns=20, end_ns=30, bar_count=10),
    ]
    calendar = SimpleNamespace(
        sessions=sessions,
        window_for_timestamp=lambda ts, n: (0 if ts < 20 else 1, 10),
    )
    timeline = NautilusEventTimeline(calendar=calendar)
    timeline.on_bar(SimpleNamespace(ts_init=5))
    timeline.on_bar(SimpleNamespace(ts_init=6))
    assert timeline.latest_occurrence(EventId.TRADING_DAY_START) == 1
    assert timeline.latest_occurrence(EventId.TRADING_SESSION_START) == 1
    timeline.on_bar(SimpleNamespace(ts_init=25))
    assert timeline.latest_occurrence(EventId.TRADING_DAY_START) == 3
    assert timeline.latest_occurrence(EventId.TRADING_SESSION_START) == 3


def test_instrument_status_and_roll_are_recurring_non_calendar_events():
    timeline = NautilusEventTimeline()
    timeline.on_bar(SimpleNamespace(ts_init=5))
    timeline.on_instrument_status("HALTED", instrument_id="AL2503")
    timeline.on_roll("2026-01-06")
    assert timeline.latest_occurrence("instrument_status:HALTED") == 1
    assert timeline.latest_occurrence("contract_roll:2026-01-06") == 1

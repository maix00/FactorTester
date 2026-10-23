"""Effective-dated commissions use NT's original FeeModel callback."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from server.services.nautilus_bridge.historical_fees import (
    FeeRuleAt,
    freeze_fee_schedule,
    freeze_fee_schedule_from_history,
    make_nautilus_fee_model,
)
from server.services.nautilus_bridge.trading_fields import (
    TradingFieldEvent,
    freeze_trading_field_timeline,
    iter_trading_field_timeline,
)
from tests.server.test_nautilus_bridge_historical_rule_events import (
    _bars,
    _engine,
    _instrument,
    _nt,
    _Probe,
)
from tests.server.test_nautilus_bridge_trading_fields import (
    SOURCE,
    _event,
    _provider,
    _rules,
)
from tools.data.field_history import FieldHistoryProvider


def _rule(at: int, per_contract: str) -> FeeRuleAt:
    zero = Decimal(0)
    rate = (zero, Decimal(per_contract))
    return FeeRuleAt(at, Decimal(10000), (rate, rate, rate))


def test_fee_rule_uses_multiplier_for_notional_and_lot_component():
    rule = FeeRuleAt(
        1, Decimal(10000),
        ((Decimal("0.00001"), Decimal(2)),
         (Decimal(0), Decimal(3)),
         (Decimal(0), Decimal(5))),
    )
    assert rule.commission("open", Decimal(2), Decimal(100)) == Decimal(24)
    assert rule.commission("close_today", Decimal(2), Decimal(100)) == Decimal(10)
    with pytest.raises(ValueError, match="unknown fill action"):
        rule.commission("buy", Decimal(1), Decimal(100))  # type: ignore[arg-type]


def test_nautilus_fee_model_uses_actual_fill_clock_across_rule_boundary():
    _nt()
    instrument = _instrument()
    first_ns = _bars(instrument, count=1)[0].ts_event

    class ClockRef:
        def __init__(self):
            self.delegate = None

        def timestamp_ns(self):
            return self.delegate.timestamp_ns()

    clock = ClockRef()
    fee = make_nautilus_fee_model(
        (_rule(first_ns, "3"), _rule(first_ns + 60_000_000_000, "7")),
        clock=clock, classify_fill=lambda order, instrument: "open", currency="CNY",
    )
    engine = _engine(instrument, fee, latency_ns=30_000_000_000)
    probe = _Probe.make(instrument, buy_at=1)
    engine.add_strategy(probe)
    clock.delegate = probe.clock
    try:
        engine.add_data(_bars(instrument, count=4))
        engine.run()
        assert len(probe.fills) == 1
        assert str(probe.fills[0].commission) == "7.00 CNY"
    finally:
        engine.dispose()


def test_nautilus_fee_model_rejects_missing_prior_rule():
    _nt()

    class Clock:
        def timestamp_ns(self):
            return 10

    fee = make_nautilus_fee_model(
        (_rule(11, "3"),), clock=Clock(),
        classify_fill=lambda order, instrument: "open", currency="CNY",
    )
    from nautilus_trader.model import Price, Quantity

    with pytest.raises(ValueError, match="no historical fee rule"):
        fee.get_commission(None, Quantity.from_str("1"), Price.from_str("100"), None)


def test_fee_schedule_uses_exact_rule_change_boundary():
    timeline = freeze_trading_field_timeline(
        source=SOURCE, instrument="AU.SHFE",
        events=[_event(20, 59, date(2025, 1, 2)),
                _event(21, 0, date(2025, 1, 3))],
        provider=_provider(), rules=_rules(),
    )
    schedule = freeze_fee_schedule(timeline)
    assert len(schedule) == 2
    assert schedule[0].rates[2][1] == 1
    assert schedule[1].rates[2][1] == 4


def test_fee_schedule_rejects_a_delayed_sample_of_a_rule_change():
    timeline = freeze_trading_field_timeline(
        source=SOURCE, instrument="AU.SHFE",
        events=[_event(20, 59, date(2025, 1, 2)),
                _event(21, 1, date(2025, 1, 3))],
        provider=_provider(), rules=_rules(),
    )
    with pytest.raises(ValueError, match="outside an exact replay boundary"):
        freeze_fee_schedule(timeline)


def test_fee_schedule_rejects_out_of_order_unchanged_samples():
    timeline = freeze_trading_field_timeline(
        source=SOURCE, instrument="AU.SHFE",
        events=[_event(20, 58, date(2025, 1, 2)),
                _event(20, 59, date(2025, 1, 2))],
        provider=_provider(), rules=_rules(),
    )
    with pytest.raises(ValueError, match="strictly time ordered"):
        freeze_fee_schedule((timeline[1], timeline[0]))


def test_fee_schedule_consumes_stream_and_keeps_only_changes():
    timeline = iter_trading_field_timeline(
        source=SOURCE, instrument="AU.SHFE",
        events=[_event(20, 58, date(2025, 1, 2)),
                _event(20, 59, date(2025, 1, 2)),
                _event(21, 0, date(2025, 1, 3))],
        provider=_provider(), rules=_rules(),
    )
    assert len(freeze_fee_schedule(timeline)) == 2


def test_sparse_fee_freeze_inserts_exact_rule_event_between_bars():
    schedule = freeze_fee_schedule_from_history(
        source=SOURCE, instrument="AU.SHFE",
        events=[_event(20, 59, date(2025, 1, 2)),
                _event(21, 1, date(2025, 1, 3))],
        provider=_provider(), rules=_rules(),
    )
    assert len(schedule) == 2
    assert schedule[1].effective_ns == pd.Timestamp(
        "2025-01-02T21:00:00", tz="Asia/Shanghai",
    ).value


def test_sparse_fee_freeze_queries_boundaries_not_every_minute(monkeypatch):
    provider = _provider()
    resolve = provider.resolve_at
    lookups = 0

    def counted(*args, **kwargs):
        nonlocal lookups
        lookups += 1
        return resolve(*args, **kwargs)

    monkeypatch.setattr(provider, "resolve_at", counted)
    start = pd.Timestamp("2025-01-02 09:00:00")
    events = (
        TradingFieldEvent(start + pd.Timedelta(minutes=i), date(2025, 1, 2))
        for i in range(1000)
    )
    schedule = freeze_fee_schedule_from_history(
        source=SOURCE, instrument="AU.SHFE", events=events,
        provider=provider, rules=_rules(),
    )
    assert len(schedule) == 2
    assert lookups < 100


def test_sparse_fee_freeze_rejects_day_only_change_without_session_boundary():
    frame = _provider().frame
    rows = frame.drop(columns=[name for name in frame if name.startswith("_")]).to_dict("records")
    rows.append({
        "provider": "SHFE:exchange-notice", "source_key": "exchange/au/day-only-fee",
        "instrument": "AU", "instrument_type": "future",
        "field_name": "CloseTodayRatioByVolume",
        "effective_trading_day": "2025-01-04", "value": 5,
    })
    events = (
        TradingFieldEvent(pd.Timestamp(at), day)
        for at, day in (("2025-01-03 09:00", date(2025, 1, 3)),
                        ("2025-01-04 09:00", date(2025, 1, 4)))
    )
    with pytest.raises(ValueError, match="outside an exact replay boundary"):
        freeze_fee_schedule_from_history(
            source=SOURCE, instrument="AU.SHFE", events=events,
            provider=FieldHistoryProvider.from_records(rows), rules=_rules(),
        )

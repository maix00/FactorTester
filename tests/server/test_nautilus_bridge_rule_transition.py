"""Actual NautilusTrader checks for effective-dated instrument updates."""

from decimal import Decimal

import pytest

from server.services.nautilus_bridge.rule_transition import (
    UnsafeRuleTransition, apply_instrument_rule_transition,
)
from tests.server.test_nautilus_bridge_historical_rule_events import (
    _Probe, _bars, _engine, _instrument, _nt,
)


def test_rule_transition_preserves_compatible_resting_order_until_it_fills():
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import Bar, OrderStatus, Price

    original = _instrument()
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=99, limit_at=1, limit_price="102.900")
    engine.add_strategy(probe)
    try:
        first = _bars(original, count=3)
        engine.add_data(first)
        engine.run(streaming=True)
        engine.clear_data()
        later = _bars(original, first_index=3, count=2)
        apply_instrument_rule_transition(
            engine, _instrument(tick="0.010"),
            effective_ns=first[-1].ts_event + 1,
            processed_through_ns=first[-1].ts_event,
            next_event_ns=later[0].ts_event,
        )
        assert str(engine.cache.instrument(original.id).price_increment) == "0.010"
        crossed = Price.from_str("102.900")
        old_bar = later[0]
        later[0] = Bar(old_bar.bar_type, crossed, crossed, crossed, crossed,
                       old_bar.volume, old_bar.ts_event, old_bar.ts_init)
        engine.add_data(later)
        engine.run(streaming=True)
        engine.clear_data()
        engine.end()
        assert engine.cache.order(probe.limit_order.client_order_id).status == OrderStatus.FILLED
        assert len(probe.fills) == 1
    finally:
        engine.dispose()


def test_rule_transition_cancels_resting_order_incompatible_with_new_tick():
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import OrderStatus

    original = _instrument()
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=99, limit_at=1, limit_price="102.905")
    engine.add_strategy(probe)
    try:
        first = _bars(original, count=3)
        engine.add_data(first)
        engine.run(streaming=True)
        engine.clear_data()
        later = _bars(original, first_index=3, count=1)
        apply_instrument_rule_transition(
            engine, _instrument(tick="0.010"),
            effective_ns=first[-1].ts_event + 1,
            processed_through_ns=first[-1].ts_event,
            next_event_ns=later[0].ts_event,
        )
        assert engine.cache.order(probe.limit_order.client_order_id).status == OrderStatus.CANCELED
        assert str(engine.cache.instrument(original.id).price_increment) == "0.010"
    finally:
        engine.dispose()


def test_open_positions_are_revalued_and_bad_boundary_is_rejected():
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import Currency

    original = _instrument()
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=1)
    engine.add_strategy(probe)
    try:
        first = _bars(original, count=3)
        engine.add_data(first)
        engine.run(streaming=True)
        engine.clear_data()
        locked_before = engine.cache.account_for_venue(original.id.venue).balance_locked(
            Currency.from_str("CNY"))
        margins_before = engine.portfolio.instrument_maintenance_margins(
            venue=original.id.venue)
        assert str(margins_before[original.id]) == "2059.00 CNY"
        updated = _instrument(tick="0.010", margin="0.04")
        next_ns = _bars(original, first_index=3, count=1)[0].ts_event
        with pytest.raises(UnsafeRuleTransition, match="processed and next events"):
            apply_instrument_rule_transition(
                engine, updated, effective_ns=first[-1].ts_event,
                processed_through_ns=first[-1].ts_event, next_event_ns=next_ns)
        apply_instrument_rule_transition(
            engine, updated, effective_ns=first[-1].ts_event + 1,
            processed_through_ns=first[-1].ts_event, next_event_ns=next_ns)
        assert engine.cache.account_for_venue(original.id.venue).balance_locked(
            Currency.from_str("CNY")) > locked_before
        assert str(engine.cache.instrument(original.id).multiplier) == "10000"
        margins_after = engine.portfolio.instrument_maintenance_margins(
            venue=original.id.venue)
        assert str(margins_after[original.id]) == "4118.00 CNY"
    finally:
        engine.dispose()


def test_exposure_free_transition_changes_new_order_tick_and_margin():
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import Currency, OrderStatus

    original = _instrument()
    updated = _instrument(tick="0.010", margin="0.04")
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=4, limit_at=5, limit_price="102.955")
    engine.add_strategy(probe)
    try:
        first = _bars(original, count=3)
        later = _bars(original, first_index=3, count=4)
        engine.add_data(first)
        engine.run(streaming=True)
        engine.clear_data()
        apply_instrument_rule_transition(
            engine, updated, effective_ns=first[-1].ts_event + 1,
            processed_through_ns=first[-1].ts_event,
            next_event_ns=later[0].ts_event)
        engine.add_data(later)
        engine.run(streaming=True)
        engine.clear_data()
        engine.end()
        assert len(probe.fills) == 1
        assert engine.cache.order(probe.limit_order.client_order_id).status == OrderStatus.REJECTED
        assert str(engine.cache.account_for_venue(original.id.venue).balance_locked(
            Currency.from_str("CNY"))) == "4119.20 CNY"
    finally:
        engine.dispose()


def test_multiplier_change_rejected_even_without_orders_or_positions():
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel

    original = _instrument()
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    try:
        first_ns = _bars(original, count=1)[0].ts_event
        with pytest.raises(UnsafeRuleTransition, match="multiplier changed"):
            apply_instrument_rule_transition(
                engine, _instrument(multiplier="20000"),
                effective_ns=first_ns + 1,
                processed_through_ns=first_ns,
                next_event_ns=first_ns + 2,
            )
        assert str(engine.cache.instrument(original.id).multiplier) == "10000"
    finally:
        engine.dispose()

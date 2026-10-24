"""Pinned NT engine experiments for changing Chinese-futures trading rules.

These are synthetic T contract events, never production orders.  They test
actual matching/account behavior rather than treating model APIs as proof.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from server.services.nautilus_bridge.market_data import (
    FuturesContractSpec, to_nautilus_instrument,
)
from tests.nautilus_runtime import require_nautilus
from tests.nautilus_source_fixture import resolved_contract_minute_source


def _nt():
    return require_nautilus()


def _instrument(*, tick="0.005", multiplier="10000", margin="0.02"):
    return to_nautilus_instrument(FuturesContractSpec(
        instrument_code="T2403", venue="CFFEX", underlying="T",
        price_increment=Decimal(tick), price_precision=3,
        multiplier=Decimal(multiplier), currency="CNY",
        activation_ns=1, expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal(margin), margin_maint=Decimal(margin),
        provenance="synthetic historical-rule engine experiment",
        resolved_source=resolved_contract_minute_source(),
    ))


def _bars(instrument, *, first_index=0, count=6):
    from nautilus_trader.model import Bar, BarType, Price, Quantity

    kind = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    first_ns = 1_704_159_060_000_000_000
    result = []
    for index in range(first_index, first_index + count):
        price = Price.from_str(f"{102.95 + index * 0.01:.3f}")
        result.append(Bar(kind, price, price, price, price,
                          Quantity.from_str("100"),
                          first_ns + index * 60_000_000_000,
                          first_ns + index * 60_000_000_000))
    return result


def _engine(instrument, fee_model, *, latency_ns=0):
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import StaticLatencyModel
    from nautilus_trader.model import AccountType, Currency, Money, OmsType, TraderId, Venue

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=TraderId.from_str("FT-HISTORY-001"),
        bypass_logging=True, run_analysis=False))
    engine.add_venue(
        venue=Venue("CFFEX"), oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=Currency.from_str("CNY"),
        starting_balances=[Money.from_str("10000000 CNY")],
        fee_model=fee_model,
        latency_model=StaticLatencyModel(base_latency_nanos=latency_ns),
    )
    engine.add_instrument(instrument)
    return engine


class _Probe:
    @staticmethod
    def make(instrument, *, buy_at=1, sell_at=None, limit_at=None,
             limit_price="102.955"):
        from nautilus_trader.model import BarType, OrderSide, Price, Quantity, TimeInForce
        from nautilus_trader.trading import Strategy

        class Probe(Strategy):
            def __new__(cls, *args, **kwargs):
                return super().__new__(cls)

            def __init__(self):
                super().__init__()
                self.bar_type = BarType.from_str(
                    f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
                self.count = 0
                self.fills = []
                self.submitted_at = []
                self.limit_order = None

            def on_start(self):
                self.subscribe_bars(self.bar_type)

            def on_bar(self, bar):
                self.count += 1
                if self.count == limit_at:
                    self.limit_order = self.order_factory.limit(
                        instrument_id=instrument.id, order_side=OrderSide.BUY,
                        quantity=Quantity.from_str("1"),
                        price=Price.from_str(limit_price),
                        time_in_force=TimeInForce.GTC)
                    self.submit_order(self.limit_order)
                side = (OrderSide.BUY if self.count == buy_at else
                        OrderSide.SELL if self.count == sell_at else None)
                if side is None:
                    return
                order = self.order_factory.market(
                    instrument_id=instrument.id, order_side=side,
                    quantity=Quantity.from_str("1"), time_in_force=TimeInForce.GTC)
                self.submitted_at.append((str(order.client_order_id), self.clock.timestamp_ns()))
                self.submit_order(order)

            def on_order_filled(self, event):
                self.fills.append(event)

        return Probe()


def test_readding_same_instrument_updates_cache_but_must_preserve_open_position():
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import Currency

    original = _instrument()
    updated = _instrument(tick="0.010", multiplier="20000", margin="0.04")
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=1, sell_at=5)
    engine.add_strategy(probe)
    cny = Currency.from_str("CNY")
    try:
        engine.add_data(_bars(original, count=3))
        engine.run(streaming=True)
        engine.clear_data()
        assert len(probe.fills) == 1
        locked_before = engine.cache.account_for_venue(original.id.venue).balance_locked(cny)
        engine.add_instrument(updated)
        assert str(engine.cache.instrument(original.id).price_increment) == "0.010"
        locked_after_update = engine.cache.account_for_venue(original.id.venue).balance_locked(cny)
        engine.add_data(_bars(updated, first_index=3, count=4))
        engine.run(streaming=True)
        engine.clear_data()
        engine.end()
        # This is the contract we need before treating historical metadata
        # events as supported.  Existing exposure is not repriced merely by
        # re-registering a new Instrument with the same id.
        assert len(probe.fills) == 2
        assert engine.get_result().total_positions == 1
        assert locked_before == locked_after_update
        assert str(engine.portfolio.realized_pnl(original.id)) == "400.00 CNY"
    finally:
        engine.dispose()


def test_custom_fee_model_can_observe_fill_time_not_just_submission_time():
    _nt()
    from nautilus_trader.execution import FeeModel
    from nautilus_trader.model import Money

    first = _bars(_instrument(), count=1)[0].ts_event

    class HistoricalFee(FeeModel):
        def __init__(self):
            self.clock = None
            self.calls = []

        def get_commission(self, order, fill_quantity, fill_px, instrument):
            fill_clock = self.clock.timestamp_ns()
            self.calls.append((order.ts_init, order.ts_last, fill_clock))
            amount = "3 CNY" if fill_clock < first + 60_000_000_000 else "7 CNY"
            return Money.from_str(amount)

    instrument = _instrument()
    fee = HistoricalFee()
    engine = _engine(instrument, fee, latency_ns=30_000_000_000)
    probe = _Probe.make(instrument, buy_at=1)
    engine.add_strategy(probe)
    fee.clock = probe.clock
    try:
        engine.add_data(_bars(instrument, count=4))
        engine.run()
        assert len(probe.fills) == 1
        assert fee.calls
        submitted, last_order, fill_clock = fee.calls[0]
        assert submitted < fill_clock
        assert last_order == submitted  # order timestamps are not the fill clock
        assert probe.fills[0].ts_event == fill_clock
        assert str(probe.fills[0].commission) == "7.00 CNY"
    finally:
        engine.dispose()


def test_official_daily_settlement_posts_variation_and_resets_open_cost_basis():
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import (
        Currency, InstrumentClose, InstrumentCloseType, Price,
    )

    instrument = _instrument()
    bars = _bars(instrument, count=6)
    engine = _engine(instrument, MakerTakerFeeModel(
        maker_rate=Decimal(0), taker_rate=Decimal(0)))
    probe = _Probe.make(instrument, buy_at=1)
    engine.add_strategy(probe)
    settlement = InstrumentClose(
        instrument_id=instrument.id,
        close_price=Price.from_str("102.970"),
        close_type=InstrumentCloseType.DAILY_SETTLEMENT,
        ts_event=bars[2].ts_event,
        ts_init=bars[2].ts_init,
    )
    cny = Currency.from_str("CNY")
    try:
        # Equal timestamps are deliberately ordered with the completed Bar
        # first, then the exchange settlement event, using the engine's
        # ordinary event path.
        engine.add_data([*bars[:3], settlement])
        engine.run(streaming=True)
        engine.clear_data()
        engine.add_data(bars[3:])
        engine.run(streaming=True)
        engine.clear_data()
        engine.end()

        assert len(probe.fills) == 1
        assert str(probe.fills[0].last_px) == "102.960"
        positions = engine.cache.positions_open(
            instrument_id=instrument.id,
            account_id=engine.cache.account_for_venue(instrument.id.venue).id,
        )
        assert len(positions) == 1
        assert str(positions[0].avg_px_open) == "102.970"
        assert str(engine.portfolio.unrealized_pnl(instrument.id)) == "300.00 CNY"
        account = engine.cache.account_for_venue(instrument.id.venue)
        assert str(account.balance_total(cny)) == "10000100.00 CNY"
    finally:
        engine.dispose()


@pytest.mark.parametrize("replace_instrument", [False, True])
def test_historical_tick_change_affects_later_limit_order_validation(replace_instrument):
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import OrderStatus

    original = _instrument()
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=99, limit_at=4)
    engine.add_strategy(probe)
    try:
        engine.add_data(_bars(original, count=3))
        engine.run(streaming=True)
        engine.clear_data()
        if replace_instrument:
            engine.add_instrument(_instrument(tick="0.010", multiplier="20000", margin="0.04"))
        engine.add_data(_bars(original, first_index=3, count=3))
        engine.run(streaming=True)
        engine.clear_data()
        engine.end()
        assert probe.limit_order is not None
        cached = engine.cache.order(probe.limit_order.client_order_id)
        assert cached is not None
        assert cached.status == (
            OrderStatus.REJECTED if replace_instrument else OrderStatus.ACCEPTED)
    finally:
        engine.dispose()


@pytest.mark.parametrize("replace_instrument", [False, True])
def test_historical_multiplier_and_margin_affect_new_position(replace_instrument):
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import Currency

    original = _instrument()
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=4)
    engine.add_strategy(probe)
    try:
        engine.add_data(_bars(original, count=3))
        engine.run(streaming=True)
        engine.clear_data()
        if replace_instrument:
            engine.add_instrument(_instrument(tick="0.010", multiplier="20000", margin="0.04"))
        engine.add_data(_bars(original, first_index=3, count=4))
        engine.run(streaming=True)
        engine.clear_data()
        engine.end()
        assert len(probe.fills) == 1
        locked = engine.cache.account_for_venue(original.id.venue).balance_locked(
            Currency.from_str("CNY"))
        assert str(locked) == ("8238.40 CNY" if replace_instrument else "2059.60 CNY")
        assert str(engine.portfolio.unrealized_pnl(original.id)) == (
            "600.00 CNY" if replace_instrument else "300.00 CNY")
    finally:
        engine.dispose()


@pytest.mark.parametrize("replace_instrument", [False, True])
def test_readding_instrument_with_resting_order_does_not_silently_preserve_matching_state(
    replace_instrument,
):
    _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import Bar, OrderStatus, Price

    original = _instrument()
    engine = _engine(original, MakerTakerFeeModel(
        maker_rate=Decimal("0"), taker_rate=Decimal("0")))
    probe = _Probe.make(original, buy_at=99, limit_at=1, limit_price="102.900")
    engine.add_strategy(probe)
    try:
        engine.add_data(_bars(original, count=3))
        engine.run(streaming=True)
        engine.clear_data()
        assert probe.limit_order is not None
        old_status = engine.cache.order(probe.limit_order.client_order_id).status
        assert old_status == OrderStatus.ACCEPTED
        if replace_instrument:
            engine.add_instrument(_instrument(tick="0.010", multiplier="20000", margin="0.04"))
        future = _bars(original, first_index=3, count=2)
        crossed = Price.from_str("102.900")
        original_bar = future[0]
        future[0] = Bar(original_bar.bar_type, crossed, crossed, crossed, crossed,
                        original_bar.volume, original_bar.ts_event, original_bar.ts_init)
        engine.add_data(future)
        engine.run(streaming=True)
        engine.clear_data()
        engine.end()
        current = engine.cache.order(probe.limit_order.client_order_id)
        assert current is not None
        # NT's add_instrument replaces the matching engine for the same ID.
        # The cache still says ACCEPTED, but the resting order disappears from
        # the new matcher and cannot fill when the price crosses.  This
        # negative test is the reason a historical-rule adapter must not call
        # add_instrument while orders are open without explicit reconciliation.
        assert current.status == (
            OrderStatus.ACCEPTED if replace_instrument else OrderStatus.FILLED)
        assert len(probe.fills) == (0 if replace_instrument else 1)
    finally:
        engine.dispose()

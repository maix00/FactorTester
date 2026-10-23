"""Pin the execution timing of a completed bar and a synthetic next open."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("submit_at_open", "expected_price"),
    [(False, 1.10), (True, 1.25)],
)
def test_completed_bar_signal_needs_open_event_for_next_open_fill(
    submit_at_open, expected_price
):
    """A zero-latency on_bar order fills at close; a distinct open tick can defer it."""
    nt = pytest.importorskip("nautilus_trader")
    assert nt.__version__ == "2.0.0rc7"

    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.core.datetime import dt_to_unix_nanos
    from nautilus_trader.execution import PerContractFeeModel
    from nautilus_trader.model import (
        AccountType, Bar, BarType, Money, OmsType, OrderSide, Price, Quantity,
        QuoteTick, TraderId, Venue,
    )
    from nautilus_trader.trading import Strategy

    example = (Path(__file__).resolve().parents[2] / "vendor/nautilus_trader"
               / "examples/backtest/synthetic_data_pnl_test.py")
    if not example.exists():
        pytest.skip("NautilusTrader submodule is not initialized")
    spec = spec_from_file_location("upstream_bar_timing_example", example)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    class SignalStrategy(Strategy):
        def __init__(self, config):
            super().__init__(config)
            self.pending = False
            self.seen_bar = False

        def on_start(self):
            self.subscribe_bars(bar_type)
            self.subscribe_quotes(instrument.id)

        def _buy(self):
            self.submit_order(self.order_factory.market(
                instrument_id=instrument.id,
                order_side=OrderSide.BUY,
                quantity=Quantity.from_str("1"),
            ))

        def on_bar(self, bar):
            if self.seen_bar:
                return
            self.seen_bar = True
            if submit_at_open:
                self.pending = True
            else:
                self._buy()

        def on_quote(self, quote):
            if self.pending:
                self.pending = False
                self._buy()

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str("TESTER-001"),
        bypass_logging=True,
    ))
    try:
        venue = Venue("SIM")
        engine.add_venue(
            venue=venue, oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN, base_currency=module.USD,
            fee_model=PerContractFeeModel(Money.from_str("0 USD")),
            starting_balances=[Money.from_str("1000000 USD")],
        )
        instrument = module.create_6E_instrument(venue)
        engine.add_instrument(instrument)
        bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
        t0 = dt_to_unix_nanos(datetime(2024, 1, 1, tzinfo=UTC))
        minute = 60_000_000_000
        first = Bar(
            bar_type=bar_type,
            open=Price.from_str("1.10000"), high=Price.from_str("1.10000"),
            low=Price.from_str("1.10000"), close=Price.from_str("1.10000"),
            volume=Quantity.from_str("100"), ts_event=t0 + minute,
            ts_init=t0 + minute,
        )
        next_open = QuoteTick(
            instrument_id=instrument.id,
            bid_price=Price.from_str("1.25000"),
            ask_price=Price.from_str("1.25000"),
            bid_size=Quantity.from_str("100"),
            ask_size=Quantity.from_str("100"),
            ts_event=t0 + minute + 1,
            ts_init=t0 + minute + 1,
        )
        second = Bar(
            bar_type=bar_type,
            open=Price.from_str("1.25000"), high=Price.from_str("1.30000"),
            low=Price.from_str("1.20000"), close=Price.from_str("1.27500"),
            volume=Quantity.from_str("100"), ts_event=t0 + 2 * minute,
            ts_init=t0 + 2 * minute,
        )
        engine.add_data([first, next_open, second])
        engine.add_strategy(SignalStrategy(module.MinimalStrategyConfig(
            instrument_id=instrument.id, bar_type=bar_type,
        )))
        engine.run()
        fills = engine.generate_order_fills_report()
        assert len(fills) == 1
        assert float(fills.iloc[0]["avg_px"]) == expected_price
    finally:
        engine.dispose()

"""End-to-end contract for native next-Bar-open execution."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from tests.nautilus_runtime import require_nautilus


def test_completed_bar_signal_matches_on_next_bar_open_without_quote_proxy():
    require_nautilus()

    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.core.datetime import dt_to_unix_nanos
    from nautilus_trader.execution import DefaultFillModel, PerContractFeeModel
    from nautilus_trader.model import (
        AccountType,
        Bar,
        BarType,
        Money,
        OmsType,
        OrderSide,
        Price,
        Quantity,
        TimeInForce,
        TraderId,
        Venue,
    )
    from nautilus_trader.trading import Strategy

    example = (Path(__file__).resolve().parents[2] / "vendor/nautilus_trader"
               / "examples/backtest/synthetic_data_pnl_test.py")
    assert example.is_file(), "Initialize vendor/nautilus_trader before running integration tests."
    spec = spec_from_file_location("upstream_bar_timing_example", example)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

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
            fill_model=DefaultFillModel(prob_fill_on_limit=1.0, prob_slippage=0.0),
            starting_balances=[Money.from_str("1000000 USD")],
            liquidity_consumption=True,
        )
        instrument = module.create_6E_instrument(venue)
        engine.add_instrument(instrument)
        bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
        t0 = dt_to_unix_nanos(datetime(2024, 1, 1, tzinfo=UTC))
        minute = 60_000_000_000
        first = Bar(
            bar_type=bar_type,
            open=Price.from_str("1.10000"), high=Price.from_str("1.11000"),
            low=Price.from_str("1.09000"), close=Price.from_str("1.10000"),
            volume=Quantity.from_str("100"), ts_event=t0 + minute,
            ts_init=t0 + minute,
        )
        second = Bar(
            bar_type=bar_type,
            open=Price.from_str("1.25000"), high=Price.from_str("1.30000"),
            low=Price.from_str("1.20000"), close=Price.from_str("1.27500"),
            volume=Quantity.from_str("100"), ts_event=t0 + 2 * minute,
            ts_init=t0 + 2 * minute,
        )

        class SignalStrategy(Strategy):
            def __init__(self, config):
                super().__init__(config)
                self.signal_ts = None

            def on_start(self):
                self.subscribe_bars(bar_type)

            def on_bar(self, bar):
                if self.signal_ts is not None:
                    return
                self.signal_ts = bar.ts_init
                order = self.order_factory.market(
                    instrument_id=instrument.id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_str("1"),
                    time_in_force=TimeInForce.AT_THE_OPEN,
                )
                self.submit_order(order)

        engine.add_data([first, second])
        strategy = SignalStrategy(module.MinimalStrategyConfig(
            instrument_id=instrument.id, bar_type=bar_type,
        ))
        engine.add_strategy(strategy)
        engine.run()
        fills = engine.generate_order_fills_report()
        assert len(fills) == 1
        assert float(fills.iloc[0]["avg_px"]) == 1.25
        assert strategy.signal_ts == first.ts_init
        assert strategy.signal_ts < second.ts_init
    finally:
        engine.dispose()

"""Optional real-engine smoke test; run with the pinned NT wheel installed."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from server.services.nautilus_bridge import export_backtest_reports


def test_real_engine_exports_execution_and_margin_history(tmp_path):
    nt = pytest.importorskip("nautilus_trader")
    assert nt.__version__ == "2.0.0rc7"
    example = (Path(__file__).resolve().parents[2] / "vendor/nautilus_trader"
               / "examples/backtest/synthetic_data_pnl_test.py")
    if not example.exists():
        pytest.skip("NautilusTrader submodule is not initialized")

    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.core.datetime import dt_to_unix_nanos
    from nautilus_trader.execution import PerContractFeeModel
    from nautilus_trader.model import (
        AccountType, Bar, BarType, Money, OmsType, Quantity, TraderId, Venue,
    )

    spec = spec_from_file_location("upstream_synthetic_example", example)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str("TESTER-001"),
    ))
    try:
        venue = Venue("SIM")
        engine.add_venue(
            venue=venue, oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN, base_currency=module.USD,
            fee_model=PerContractFeeModel(Money.from_str("2.50 USD")),
            starting_balances=[Money.from_str("1000000 USD")],
        )
        instrument = module.create_6E_instrument(venue)
        engine.add_instrument(instrument)
        bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
        first = dt_to_unix_nanos(datetime(2024, 1, 1, tzinfo=UTC))
        bars = [Bar(
            bar_type=bar_type,
            open=instrument.make_price(1.1 + i * .0001),
            high=instrument.make_price(1.2 + i * .0001),
            low=instrument.make_price(1.1 + i * .0001),
            close=instrument.make_price(1.1 + i * .0001),
            volume=Quantity.from_str("100"),
            ts_event=first + i * 60_000_000_000,
            ts_init=first + i * 60_000_000_000,
        ) for i in range(12)]
        engine.add_data(bars)
        engine.add_strategy(module.MinimalStrategy(
            config=module.MinimalStrategyConfig(
                instrument_id=instrument.id, bar_type=bar_type,
            ),
        ))
        engine.run()

        destination = tmp_path / "native"
        receipt = export_backtest_reports(engine, destination, venue=venue)
        assert len((destination / "fills.csv").read_text().splitlines()) == 3
        assert "MarginBalance" in (destination / "account.csv").read_text()
        assert (destination / "tearsheet.html").stat().st_size > 1000
        assert len(receipt["artifacts"]) == 5
    finally:
        engine.dispose()

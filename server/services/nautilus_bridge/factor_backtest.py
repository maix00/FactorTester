"""Bounded real Nautilus run of a frozen FactorExpr strategy on one catalog."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from server.services.nautilus_bridge.backtest_runner import _load_input, ReplayInput
from server.services.nautilus_bridge.factor_stream import build_nautilus_factor_strategy
from server.services.nautilus_bridge.reports import export_backtest_reports
from tools.factors.expr.core import FactorExpr
from tools.data.types.time_freq import DataFreq


def run_factor_strategy_replay(
    *, input: ReplayInput, factor_ref: str, expression: FactorExpr,
    product: Any, output_dir: Path, max_bars: int = 8,
    factor_field: str = "CLOSE_ADJUSTED",
) -> dict[str, Any]:
    """Run one FactorExpr strategy in Nautilus and export native reports."""
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import (
        AccountType, BarType, Currency, Money, OmsType, OrderSide, Quantity,
        TimeInForce, TraderId, Venue,
    )
    from nautilus_trader.trading import Strategy

    folder, catalog, receipt, instrument = _load_input(input)
    bar_type = BarType.from_str(str(receipt["bar_type"]))
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str("FT-FACTOR-001"),
    ))
    venue = Venue("CFFEX")
    engine.add_venue(
        venue=venue, oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=Currency.from_str("CNY"),
        starting_balances=[Money.from_str("1000000 CNY")],
        fee_model=MakerTakerFeeModel(
            maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(instrument)
    publications: list[Any] = []

    class Trader(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self.factor = build_nautilus_factor_strategy(
                factor_ref=factor_ref, expression=expression, products=(product,),
                bar_types_by_product={product: bar_type}, source_freq=DataFreq.MIN1,
                bar_clock=lambda _p, bar: _clock(bar),
                factor_fields=lambda _p, bar: {factor_field: float(bar.close)},
                first_executable_at=lambda clocks: max(
                    clock.available_at_ns for clock in clocks.values()) + 1,
                on_publication=publications.append,
            )
            self.seen = 0

        def on_start(self) -> None:
            self.subscribe_bars(bar_type)

        def on_bar(self, bar) -> None:
            self.factor.on_bar(bar)
            self.seen += 1
            if self.seen == 2:
                self.submit_order(self.order_factory.market(
                    instrument_id=bar.bar_type.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_str("1"),
                    time_in_force=TimeInForce.AT_THE_OPEN,
                ))

    engine.add_strategy(Trader())
    bars = catalog.query_bars(identifiers=[receipt["bar_type"]], start=0, end=2**63 - 1)
    if len(bars) > max_bars:
        raise ValueError("factor replay exceeds explicit bar cap")
    engine.add_data(list(bars))
    engine.run()
    engine.end()
    reports = export_backtest_reports(engine, Path(output_dir), venue=venue)
    return {
        "engine": "nautilus_trader",
        "bars": len(bars),
        "publications": len(publications),
        "factor_ref": factor_ref,
        "reports": reports,
        "order_count": engine.get_result().total_orders,
        "catalog": str(folder),
    }


def _clock(bar: Any):
    from server.services.nautilus_bridge.market_data import BarClock
    minute = 60_000_000_000
    end = int(bar.ts_event)
    return BarClock(None, None, end - minute, end, int(bar.ts_init), "factor bar")

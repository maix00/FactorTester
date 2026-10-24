"""T/TL event-time factor semantics before wiring a live NT strategy."""

from __future__ import annotations

from datetime import datetime
import math
import sys
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

from server.services.nautilus_bridge.factor_stream import (
    EventTimeFactorStream,
    build_nautilus_factor_strategy,
)
from server.services.nautilus_bridge.market_data import BarClock, minute_clock
from tools.data.types import DataFreq
from tools.factors.expr import CLOSE, ConstExpr, SignalAlign
from tools.factors.expr.streaming.incremental import UnsupportedStreamingFactor
from tests.nautilus_runtime import require_nautilus


REF = "factor:v2:nupERUpfhFNGFIB4AT3UfJiJaTRbaC0r5V1nUU9R6aM"


def _slice(stream, minute, t_close, tl_close, *, delay_ns=0):
    dt = datetime(2024, 1, 2, 9, minute)
    ns = int(pd.Timestamp(dt, tz="Asia/Shanghai").timestamp() * 1_000_000_000)
    clock = minute_clock(dt, ns, raw_unit="ns", available_delay_ns=delay_ns)
    result = stream.on_completed_slice(
        clocks_by_product={"T": clock, "TL": clock},
        fields_by_product={
            "T": {"CLOSE_ADJUSTED": t_close},
            "TL": {"CLOSE_ADJUSTED": tl_close},
        },
        first_executable_at_ns=clock.available_at_ns + 60_000_000_000,
    )
    return clock, result


def test_minute_nested_factor_holds_last_completed_inner_period_for_t_and_tl():
    stream = EventTimeFactorStream(factor_ref=REF,
        expression=SignalAlign(CLOSE, "2m") + CLOSE,
        products=("T", "TL"), source_freq=DataFreq.MIN1)
    observed = []
    prior = None
    for minute, t, tl in [(31, 1, 10), (32, 2, 20), (33, 3, 30), (34, 4, 40)]:
        clock, pub = _slice(stream, minute, t, tl)
        observed.append((pub.values["T"], pub.values["TL"]))
        assert pub.formed_at_ns == clock.interval_end_ns
        assert stream.latest_as_of(clock.interval_end_ns) is pub
        assert stream.tradable_as_of(clock.interval_end_ns) is prior
        assert stream.tradable_as_of(pub.first_executable_at_ns) is pub
        prior = pub
    assert math.isnan(observed[0][0]) and math.isnan(observed[0][1])
    assert observed[1:] == [(4.0, 40.0), (5.0, 50.0), (8.0, 80.0)]


def test_where_uses_same_completed_slice_and_never_a_future_branch():
    expr = SignalAlign(CLOSE, "2m").where(
        CLOSE > ConstExpr(2.0), other=ConstExpr(-1.0))
    stream = EventTimeFactorStream(factor_ref=REF, expression=expr,
        products=("T", "TL"), source_freq=DataFreq.MIN1)
    _slice(stream, 31, 1, 10)
    _, at_32 = _slice(stream, 32, 2, 20)
    assert at_32.values == {"T": -1.0, "TL": 20.0}
    _, at_33 = _slice(stream, 33, 3, 1)
    assert at_33.values == {"T": 2.0, "TL": -1.0}
    _, at_34 = _slice(stream, 34, 4, 40)
    assert at_34.values == {"T": 4.0, "TL": 40.0}


def test_visibility_delay_and_next_open_are_distinct():
    stream = EventTimeFactorStream(factor_ref=REF, expression=CLOSE,
        products=("T", "TL"), source_freq=DataFreq.MIN1)
    clock, pub = _slice(stream, 31, 102.1, 103.2, delay_ns=2_000_000_000)
    assert stream.latest_as_of(clock.interval_end_ns) is None
    assert stream.latest_as_of(pub.available_at_ns) is pub
    assert stream.tradable_as_of(pub.available_at_ns) is None


def test_previous_value_remains_visible_while_new_slice_waits_for_release():
    stream = EventTimeFactorStream(factor_ref=REF, expression=CLOSE,
        products=("T", "TL"), source_freq=DataFreq.MIN1)
    _, old = _slice(stream, 31, 102.1, 103.2)
    clock, newer = _slice(stream, 32, 102.2, 103.3, delay_ns=5_000_000_000)
    assert stream.latest_as_of(clock.interval_end_ns) is old
    assert stream.latest_as_of(newer.available_at_ns) is newer


def test_incomplete_out_of_order_or_same_bar_execution_is_rejected():
    stream = EventTimeFactorStream(factor_ref=REF, expression=CLOSE,
        products=("T", "TL"), source_freq=DataFreq.MIN1)
    dt = datetime(2024, 1, 2, 9, 31)
    ns = int(pd.Timestamp(dt, tz="Asia/Shanghai").timestamp() * 1e9)
    clock = minute_clock(dt, ns, raw_unit="ns")
    with pytest.raises(ValueError, match="exactly"):
        stream.on_completed_slice(clocks_by_product={"T": clock},
            fields_by_product={"T": {"CLOSE_ADJUSTED": 1}},
            first_executable_at_ns=ns + 60_000_000_000)
    with pytest.raises(ValueError, match="follow"):
        stream.on_completed_slice(clocks_by_product={"T": clock, "TL": clock},
            fields_by_product={"T": {"CLOSE_ADJUSTED": 1}, "TL": {"CLOSE_ADJUSTED": 2}},
            first_executable_at_ns=ns)
    _slice(stream, 31, 1, 2)
    with pytest.raises(ValueError, match="increasing"):
        _slice(stream, 31, 1, 2)


def test_daily_nested_alignment_is_explicitly_unavailable_until_calendar_close_compiler():
    with pytest.raises(UnsupportedStreamingFactor, match="session-calendar close"):
        EventTimeFactorStream(factor_ref=REF,
            expression=SignalAlign(CLOSE, "1d"),
            products=("T", "TL"), source_freq=DataFreq.MIN1)


def test_nautilus_strategy_buffers_one_complete_cross_sectional_slice(monkeypatch):
    trading = ModuleType("nautilus_trader.trading")

    class Strategy:
        def __init__(self):
            self.subscriptions = []

        def subscribe_bars(self, bar_type):
            self.subscriptions.append(bar_type)

    trading.Strategy = Strategy
    package = ModuleType("nautilus_trader")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "nautilus_trader", package)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading", trading)

    bar_types = {
        "T": SimpleNamespace(instrument_id="T.CFFEX"),
        "TL": SimpleNamespace(instrument_id="TL.CFFEX"),
    }
    publications = []
    minute_ns = 60_000_000_000

    def clock_for_bar(_product, bar):
        end_ns = int(bar.ts_event)
        return BarClock(None, None, end_ns - minute_ns, end_ns,
                        int(bar.ts_init), "test bar")

    strategy = build_nautilus_factor_strategy(
        factor_ref=REF,
        expression=CLOSE,
        products=("T", "TL"),
        bar_types_by_product=bar_types,
        source_freq=DataFreq.MIN1,
        bar_clock=clock_for_bar,
        factor_fields=lambda product, bar: {
            "CLOSE_ADJUSTED": float(bar.close),
        },
        first_executable_at=lambda clocks: max(
            clock.available_at_ns for clock in clocks.values()
        ) + 1,
        on_publication=publications.append,
    )
    strategy.on_start()
    assert strategy.subscriptions == list(bar_types.values())

    end_ns = 1_000_000_000_000
    for product, instrument_id, value in (
        ("TL", "TL.CFFEX", 10.0), ("T", "T.CFFEX", 100.0),
    ):
        strategy.on_bar(SimpleNamespace(
            bar_type=SimpleNamespace(instrument_id=instrument_id),
            ts_event=end_ns,
            ts_init=end_ns,
            close=value,
        ))

    assert len(publications) == 1
    assert publications[0].values == {"T": 100.0, "TL": 10.0}
    assert not strategy._pending_clocks
    assert not strategy._pending_fields

    strategy.on_bar(SimpleNamespace(
        bar_type=SimpleNamespace(instrument_id="T.CFFEX"),
        ts_event=end_ns + minute_ns,
        ts_init=end_ns + minute_ns,
        close=101.0,
    ))
    with pytest.raises(ValueError, match="complete cross-sectional slice"):
        strategy.on_bar(SimpleNamespace(
            bar_type=SimpleNamespace(instrument_id="T.CFFEX"),
            ts_event=end_ns + 2 * minute_ns,
            ts_init=end_ns + 2 * minute_ns,
            close=102.0,
        ))


def test_nautilus_on_bar_drives_factor_calculation_without_a_market_panel():
    require_nautilus()
    from datetime import UTC, datetime
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.core.datetime import dt_to_unix_nanos
    from nautilus_trader.execution import PerContractFeeModel
    from nautilus_trader.model import (
        AccountType, Bar, BarType, Money, OmsType, Quantity, TraderId, Venue,
    )

    example = (Path(__file__).resolve().parents[2] / "vendor/nautilus_trader"
               / "examples/backtest/synthetic_data_pnl_test.py")
    assert example.is_file(), "Initialize vendor/nautilus_trader before running integration tests."
    spec = spec_from_file_location("upstream_factor_stream_example", example)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    venue = Venue("SIM")
    instrument = module.create_6E_instrument(venue)
    bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
    product = str(instrument.id)
    publications = []
    minute_ns = 60_000_000_000

    def clock_for_bar(_product, bar):
        end_ns = int(bar.ts_event)
        available_ns = max(end_ns, int(bar.ts_init))
        return BarClock(None, None, end_ns - minute_ns, end_ns,
                        available_ns, "Nautilus completed bar")

    strategy = build_nautilus_factor_strategy(
        factor_ref=REF,
        expression=CLOSE,
        products=(product,),
        bar_types_by_product={product: bar_type},
        source_freq=DataFreq.MIN1,
        bar_clock=clock_for_bar,
        factor_fields=lambda _product, bar: {
            "CLOSE_ADJUSTED": float(bar.close),
        },
        first_executable_at=lambda clocks: max(
            clock.available_at_ns for clock in clocks.values()
        ) + 1,
        on_publication=publications.append,
    )
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str("FT-FACTOR-STREAM-001"),
        bypass_logging=True,
    ))
    try:
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=module.USD,
            fee_model=PerContractFeeModel(Money.from_str("0 USD")),
            starting_balances=[Money.from_str("1000000 USD")],
        )
        engine.add_instrument(instrument)
        start_ns = dt_to_unix_nanos(datetime(2024, 1, 1, tzinfo=UTC))
        values = [1.1000, 1.1002, 1.1005]
        engine.add_data([
            Bar(
                bar_type=bar_type,
                open=instrument.make_price(value),
                high=instrument.make_price(value),
                low=instrument.make_price(value),
                close=instrument.make_price(value),
                volume=Quantity.from_str("100"),
                ts_event=start_ns + i * minute_ns,
                ts_init=start_ns + i * minute_ns,
            )
            for i, value in enumerate(values, start=1)
        ])
        engine.add_strategy(strategy)
        engine.run()

        assert [item.formed_at_ns for item in publications] == [
            start_ns + i * minute_ns for i in range(1, len(values) + 1)
        ]
        assert [item.values[product] for item in publications] == pytest.approx(values)
    finally:
        engine.dispose()

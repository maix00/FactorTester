"""Bounded local NautilusTrader replay of already frozen T/TL catalogs.

This is an isolated validation entry point, not a Job submission API or a
claim that a paper factor has been reproduced.  The only optional orders are
an explicitly synthetic engine probe.  Fees/margin in a probe are test inputs.
"""

from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from server.services.nautilus_bridge.reports import export_backtest_reports
from server.services.nautilus_bridge.version import NAUTILUS_VERSION

MINUTE_NS = 60_000_000_000


def _rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value * (1024 if sys.platform.startswith("linux") else 1))


@dataclass(frozen=True, slots=True)
class ReplayInput:
    catalog_dir: Path
    expected_contract_uid: str


@dataclass(frozen=True, slots=True)
class ReplayReceipt:
    schema_version: int
    engine: str
    mode: Literal["market_only", "synthetic_order_probe"]
    factor_claim: str
    input_receipts: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    input_bars: int
    next_bar_open_orders: int
    first_event_ns: int
    last_event_ns: int
    position_cost_basis: str
    position_cost_basis_by_instrument: dict[str, str]
    batch_count: int
    max_batch_bars: int
    max_batch_events: int
    elapsed_ms: float
    process_peak_rss_bytes: int
    native_iterations: int
    native_orders: int
    native_positions: int
    probe_fill_prices: tuple[str, ...]
    execution_assumptions: tuple[str, ...]
    reports: dict[str, object]


def _load_input(item: ReplayInput):
    from nautilus_trader.persistence import ParquetDataCatalog

    folder = Path(item.catalog_dir).resolve(strict=True)
    receipt_path = folder / "factor_tester_catalog_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("engine") != f"NautilusTrader {NAUTILUS_VERSION}":
        raise ValueError("catalog was not staged with pinned NautilusTrader")
    if receipt.get("contract_uid") != item.expected_contract_uid:
        raise ValueError("catalog contract UID does not match the requested identity")
    if "|F|" not in str(item.expected_contract_uid):
        raise ValueError("probe accepts futures contracts only")
    for file in receipt.get("catalog_files", ()):
        path = (folder / file["path"]).resolve(strict=True)
        if not path.is_relative_to(folder):
            raise ValueError("catalog receipt path escapes its directory")
        if path.stat().st_size != file["bytes"]:
            raise ValueError("catalog bytes differ from frozen receipt")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != file["sha256"]:
            raise ValueError("catalog hash differs from frozen receipt")
    catalog = ParquetDataCatalog(str(folder))
    instruments = catalog.instruments(instrument_ids=[receipt["instrument_id"]])
    if len(instruments) != 1 or str(instruments[0].id) != receipt["instrument_id"]:
        raise ValueError("catalog instrument identity differs from its receipt")
    return folder, catalog, receipt, instruments[0]


def run_small_catalog_replay(
    inputs: tuple[ReplayInput, ...], output_dir: Path, *,
    max_input_bars: int = 2_000, batch_minutes: int = 20,
    synthetic_order_probe: bool = False,
    frozen_factor_ref: str | None = None,
    position_cost_basis: str = "WEIGHTED_AVERAGE",
    position_cost_basis_by_instrument: Mapping[str, str] | None = None,
) -> ReplayReceipt:
    """Replay a tiny, receipt-checked window with bounded native data batches.

    A frozen factor ref alone is insufficient: its resolved FactorExpr, Job
    configuration, source version and next-Bar timing must all be proven.
    Until then this entry refuses factor execution rather than substituting a
    different factor or claiming original-paper performance.
    """
    if frozen_factor_ref is not None:
        raise NotImplementedError(
            "a ref alone is not a resolved frozen FactorExpr/Job; factor strategy disabled"
        )
    if not inputs or len(inputs) > 2 or not 1 <= max_input_bars <= 10_000:
        raise ValueError("probe requires one or two inputs and a small explicit bar cap")
    if not 1 <= batch_minutes <= 1_000:
        raise ValueError("invalid streaming batch interval")
    if Path(output_dir).exists():
        raise FileExistsError(output_dir)

    from nautilus_trader import __version__ as nt_version
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import ExecutionEngineConfig
    from nautilus_trader.execution import DefaultFillModel
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import (
        AccountType,
        Bar,
        Currency,
        InstrumentId,
        Money,
        OmsType,
        PositionCostBasis,
        TraderId,
        Venue,
    )

    if nt_version != NAUTILUS_VERSION:
        raise RuntimeError(f"NautilusTrader pin mismatch: {nt_version}")
    cost_basis = PositionCostBasis.from_str(position_cost_basis)
    opened = tuple(_load_input(item) for item in inputs)
    ids = tuple(row[2]["instrument_id"] for row in opened)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate instrument")
    raw_basis_overrides = (
        {} if position_cost_basis_by_instrument is None
        else position_cost_basis_by_instrument
    )
    if not isinstance(raw_basis_overrides, Mapping):
        raise ValueError("position_cost_basis_by_instrument must be a mapping")
    unknown_basis_ids = set(raw_basis_overrides) - set(ids)
    if unknown_basis_ids:
        raise ValueError(
            "position-cost-basis exceptions are outside the frozen replay scope: "
            + ", ".join(sorted(map(str, unknown_basis_ids)))
        )
    basis_overrides = {
        instrument_id: PositionCostBasis.from_str(value)
        for instrument_id, value in raw_basis_overrides.items()
    }
    basis_overrides_for_receipt = {
        instrument_id: str(value).rsplit(".", 1)[-1]
        for instrument_id, value in raw_basis_overrides.items()
    }
    if sum(int(row[2]["selected_count"]) for row in opened) > max_input_bars:
        raise ValueError("catalog receipts exceed the explicit replay bar cap")
    first_ns = min(int(row[2]["first_event_ns"]) for row in opened)
    first_available_ns = min(int(row[2]["first_available_ns"]) for row in opened)
    last_ns = max(int(row[2]["last_event_ns"]) for row in opened)
    if last_ns - first_ns > 2 * 86_400 * 1_000_000_000:
        raise ValueError("isolated replay window may not span more than two days")
    venue = Venue("CFFEX")
    started = time.perf_counter()
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str("FT-PROBE-001"),
        exec_engine=ExecutionEngineConfig(
            position_cost_basis=cost_basis,
            position_cost_basis_by_instrument={
                InstrumentId.from_str(instrument_id): basis
                for instrument_id, basis in basis_overrides.items()
            },
        )))
    try:
        # Test-only account settings.  No fee/margin inference from prices.
        engine.add_venue(
            venue=venue, oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN, base_currency=Currency.from_str("CNY"),
            starting_balances=[Money.from_str("1000000 CNY")],
            fill_model=(DefaultFillModel(
                prob_fill_on_limit=1.0, prob_slippage=0.0,
            ) if synthetic_order_probe else None),
            fee_model=MakerTakerFeeModel(
                maker_rate=Decimal(0), taker_rate=Decimal(0)),
            liquidity_consumption=synthetic_order_probe,
        )
        for _, _, _, instrument in opened:
            engine.add_instrument(instrument)
        if synthetic_order_probe:
            from nautilus_trader.model import BarType, OrderSide, Quantity, TimeInForce
            from nautilus_trader.trading import Strategy

            class ProbeStrategy(Strategy):
                def __new__(cls, *args, **kwargs):
                    return super().__new__(cls)

                def __init__(self, instrument_id: str, bar_type: str):
                    super().__init__()
                    self.instrument_id = instrument_id
                    self.bar_type = BarType.from_str(bar_type)
                    self.seen = 0

                def on_start(self) -> None:
                    self.subscribe_bars(self.bar_type)

                def on_bar(self, bar) -> None:
                    self.seen += 1
                    if self.seen not in (2, 5):
                        return
                    side = (
                        OrderSide.BUY if self.seen == 2 else OrderSide.SELL
                    )
                    order = self.order_factory.market(
                        instrument_id=bar.bar_type.instrument_id,
                        order_side=side,
                        quantity=Quantity.from_str("1"),
                        time_in_force=TimeInForce.AT_THE_OPEN,
                    )
                    self.submit_order(order)

            probe_strategy = ProbeStrategy(ids[0], opened[0][2]["bar_type"])
            engine.add_strategy(probe_strategy)
        else:
            probe_strategy = None

        processed = batches = largest_batch = largest_event_batch = 0
        next_bar_open_orders = 0
        timeline_first_ns = first_available_ns
        next_start_ns = timeline_first_ns
        previous_batch_end_ns = None
        probe_seen = 0
        probe_order_pending = False
        expected_probe_fill_prices: list[str] = []
        step_ns = batch_minutes * MINUTE_NS
        for begin in range(first_ns, last_ns + 1, step_ns):
            end = min(begin + step_ns - 1, last_ns)
            bars = []
            for _, catalog, receipt, _ in opened:
                bars.extend(catalog.query_bars(
                    identifiers=[receipt["bar_type"]], start=begin, end=end))
            if not bars:
                continue
            processed += len(bars)
            if processed > max_input_bars:
                raise ValueError("catalog query exceeds explicit replay bar cap")
            largest_batch = max(largest_batch, len(bars))
            if synthetic_order_probe:
                for bar in sorted(bars, key=lambda item: int(item.ts_init)):
                    if str(bar.bar_type.instrument_id) != ids[0]:
                        continue
                    if probe_order_pending:
                        expected_probe_fill_prices.append(str(bar.open))
                        probe_order_pending = False
                    probe_seen += 1
                    if probe_seen in (2, 5):
                        probe_order_pending = True
                        next_bar_open_orders += 1
            events = list(bars)
            events.sort(key=lambda item: (
                int(item.ts_init), 0 if isinstance(item, Bar) else 1,
            ))
            largest_event_batch = max(largest_event_batch, len(events))
            batch_start_ns = min(int(event.ts_init) for event in events)
            batch_end_ns = max(int(event.ts_init) for event in events)
            if previous_batch_end_ns is not None and batch_start_ns <= previous_batch_end_ns:
                raise ValueError(
                    "streaming batch splits or reorders one NautilusTrader replay timestamp"
                )
            if batch_end_ns < next_start_ns:
                raise ValueError("streaming replay clock would move backwards")
            # add_data copies into NT-owned storage.  Discard the short Python
            # batch immediately after loading, then run and clear native data.
            engine.add_data(events)
            bars.clear()
            events.clear()
            engine.run(start=next_start_ns, end=batch_end_ns, streaming=True)
            engine.clear_data()
            previous_batch_end_ns = batch_end_ns
            # Keep the engine clock at the previous batch boundary. NautilusTrader
            # advances scheduled timers across gaps before delivering the next bar.
            next_start_ns = batch_end_ns
            batches += 1
        expected = sum(int(row[2]["selected_count"]) for row in opened)
        if processed != expected:
            raise ValueError(f"catalog replay count {processed} != receipts {expected}")
        engine.end()
        result = engine.get_result()
        probe_fill_prices: tuple[str, ...] = ()
        if synthetic_order_probe:
            fills = engine.generate_order_fills_report()
            probe_fill_prices = tuple(str(value) for value in fills["avg_px"].tolist())
            expected_prices = tuple(expected_probe_fill_prices)
            if len(probe_fill_prices) != len(expected_prices):
                raise RuntimeError(
                    "next-Bar-open probe did not fill every submitted market order"
                )
            for actual, expected_price in zip(probe_fill_prices, expected_prices, strict=True):
                if Decimal(actual) != Decimal(expected_price):
                    raise RuntimeError(
                        f"next-open fill {actual} differs from opening quote {expected_price}"
                    )
        reports = export_backtest_reports(engine, Path(output_dir), venue=venue)
        receipt = ReplayReceipt(
            schema_version=3, engine=f"NautilusTrader {nt_version}",
            mode="synthetic_order_probe" if synthetic_order_probe else "market_only",
            factor_claim="none; no frozen FactorExpr/Job supplied",
            input_receipts=tuple(str(row[0] / "factor_tester_catalog_receipt.json")
                                 for row in opened),
            instrument_ids=ids, input_bars=processed,
            next_bar_open_orders=next_bar_open_orders,
            first_event_ns=timeline_first_ns, last_event_ns=last_ns,
            position_cost_basis=str(cost_basis).rsplit(".", 1)[-1],
            position_cost_basis_by_instrument=basis_overrides_for_receipt,
            batch_count=batches, max_batch_bars=largest_batch,
            max_batch_events=largest_event_batch,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            process_peak_rss_bytes=_rss_bytes(),
            native_iterations=result.iterations,
            native_orders=result.total_orders,
            native_positions=result.total_positions,
            probe_fill_prices=probe_fill_prices,
            execution_assumptions=(
                (
                    "Signal is formed in a completed Bar callback; the market order is submitted with AT_THE_OPEN.",
                    "NautilusTrader matches it on the next Bar's native open leg at that Bar.open.",
                    "The native Bar matching book and liquidity_consumption setting cap the open-leg volume shared by orders.",
                    "The timing probe pins Nautilus DefaultFillModel slippage to zero to verify the exact open price; production slippage must be frozen through a compatible FillModel policy.",
                    "This uses NautilusTrader's OHLC volume allocation at the open leg; it is not a configurable whole-Bar participation-rate cap.",
                ) if synthetic_order_probe else (
                    "No order execution requested; source bars are replayed directly without synthetic quotes.",
                )
            ),
            reports=reports,
        )
        (Path(output_dir) / "replay_receipt.json").write_text(
            json.dumps(asdict(receipt), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return receipt
    finally:
        engine.dispose()

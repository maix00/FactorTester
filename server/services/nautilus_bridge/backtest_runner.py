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
    native_settlements: int
    source_inputs: tuple[dict[str, str], ...]
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


def preflight_catalogs(opened, *, max_input_bars: int) -> tuple[int, int, int]:
    """Check frozen row counts before any Bar query or engine allocation.

    Counts belong to the hash-verified receipts, not a caller's estimate.
    Query boundaries use ts_init, as does Nautilus' Parquet catalog.
    """
    if isinstance(max_input_bars, bool) or not isinstance(max_input_bars, int) or max_input_bars <= 0:
        raise ValueError("replay bar cap must be a positive integer")
    rows = tuple(opened)
    if not rows:
        raise ValueError("replay needs at least one catalog")
    counts = [int(row[2]["selected_count"]) for row in rows]
    if any(count <= 0 for count in counts):
        raise ValueError("catalog receipt needs a positive frozen row count")
    total = sum(counts)
    if total > max_input_bars:
        raise ValueError("catalog receipts exceed the explicit replay bar cap")
    first = min(int(row[2]["first_available_ns"]) for row in rows)
    last = max(int(row[2]["last_available_ns"]) for row in rows)
    if first < 0 or last < first:
        raise ValueError("catalog receipt has an invalid replay range")
    return first, last, total


from traderesearch_data.shared_cache import batch_input_budget


@batch_input_budget
def replay_catalog_batches(engine, opened, *, max_input_bars: int, batch_minutes: int = 20,
                           max_batch_bars: int = 250_000,
                           query_memory_limit_bytes: int = 128 * 1024 * 1024):
    """Use Nautilus' native Catalog merge/replay on the configured engine.

    Only frozen receipt validation/configuration crosses Python here. Market
    batches never enter a Python merge, list conversion or add_data loop.
    """
    if isinstance(batch_minutes, bool) or not isinstance(batch_minutes, int) or batch_minutes <= 0:
        raise ValueError("batch_minutes must be a positive integer")
    rows = tuple(opened)
    first, last, expected = preflight_catalogs(rows, max_input_bars=max_input_bars)
    if isinstance(max_batch_bars, bool) or not isinstance(max_batch_bars, int) or max_batch_bars < 1:
        raise ValueError("max_batch_bars must be a positive integer")
    if (isinstance(query_memory_limit_bytes, bool) or not isinstance(query_memory_limit_bytes, int)
            or query_memory_limit_bytes < 1):
        raise ValueError("query memory limit must be a positive integer")
    from nautilus_trader.config import BacktestDataConfig
    from nautilus_trader.model import InstrumentId, NautilusDataType
    data = [BacktestDataConfig(
        data_type=NautilusDataType.Bar, catalog_path=str(folder),
        bar_types=[str(receipt["bar_type"])],
        # One streaming table per homogeneous catalog directory. The native
        # default opens one buffered query per file, multiplying prefetch/RSS.
        optimize_file_loading=True,
        start_time=int(receipt["first_available_ns"]),
        end_time=int(receipt["last_available_ns"]),
    ) for folder, _catalog, receipt, _instrument in rows]
    settlement_count = 0
    for folder, _catalog, receipt, instrument in rows:
        records = tuple(receipt.get("settlement_records") or ())
        if not records:
            continue
        settlement_count += len(records)
        data.append(BacktestDataConfig(
            data_type=NautilusDataType.InstrumentClose, catalog_path=str(folder),
            instrument_id=InstrumentId.from_str(str(instrument.id)),
            optimize_file_loading=True,
            start_time=min(int(item["event_ns"]) for item in records),
            end_time=max(int(item["event_ns"]) for item in records),
        ))
    total, batches, largest, source_counts = engine.run_catalogs(
        data=data, chunk_size=min(batch_minutes * len(rows), max_batch_bars, 1_000_000),
        max_chunk_events=max_batch_bars, start=first, end=last,
        query_memory_limit_bytes=max(1, query_memory_limit_bytes // len(rows)),
    )
    if total < settlement_count:
        raise ValueError("native replay total is smaller than settlement events")
    total -= settlement_count
    expected_source_counts = []
    for row in rows:
        expected_source_counts.append(int(row[2]["selected_count"]))
        settlement = len(tuple(row[2].get("settlement_records") or ()))
        if settlement:
            expected_source_counts.append(settlement)
    if list(source_counts) != expected_source_counts:
        raise ValueError("native per-source replay counts differ from frozen receipts")
    if total != expected or engine.get_result().iterations != expected + settlement_count:
        raise ValueError("native catalog replay count differs from the frozen receipts")
    source_inputs = tuple({
        "bundle_id": str(receipt.get("bundle_id") or ""),
        "bundle_version": str(receipt.get("bundle_version") or ""),
        "bundle_fingerprint": str(receipt.get("bundle_fingerprint") or ""),
        "member_id": str(receipt.get("member_id") or ""),
        "contract_uid": str(receipt.get("contract_uid") or ""),
    } for _folder, _catalog, receipt, _instrument in rows)
    return {"bars": total, "settlements": settlement_count,
            "source_inputs": source_inputs,
            "batch_count": batches, "max_batch_bars": largest}


def run_small_catalog_replay(
    inputs: tuple[ReplayInput, ...], output_dir: Path, *,
    max_input_bars: int = 2_000, batch_minutes: int = 20,
    max_batch_bars: int = 250_000,
    max_replay_days: int = 2,
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
    if isinstance(max_replay_days, bool) or not isinstance(max_replay_days, int) or max_replay_days <= 0:
        raise ValueError("max_replay_days must be a positive integer")
    preflight_catalogs(opened, max_input_bars=max_input_bars)
    first_ns = min(int(row[2]["first_event_ns"]) for row in opened)
    first_available_ns = min(int(row[2]["first_available_ns"]) for row in opened)
    last_ns = max(int(row[2]["last_event_ns"]) for row in opened)
    if last_ns - first_ns > max_replay_days * 86_400 * 1_000_000_000:
        raise ValueError(f"isolated replay window exceeds {max_replay_days} days")
    venue = Venue("CFFEX")
    started = time.perf_counter()
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str("FT-PROBE-001"),
        shutdown_on_error=True,
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
                    self.submitted = 0
                    self.pending = False
                    self.expected_fill_prices: list[str] = []

                def on_start(self) -> None:
                    self.subscribe_bars(self.bar_type)

                def on_bar(self, bar) -> None:
                    if self.pending:
                        self.expected_fill_prices.append(str(bar.open))
                        self.pending = False
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
                    self.submitted += 1
                    self.pending = True

            probe_strategy = ProbeStrategy(ids[0], opened[0][2]["bar_type"])
            engine.add_strategy(probe_strategy)
        else:
            probe_strategy = None

        replay = replay_catalog_batches(
            engine, opened, max_input_bars=max_input_bars,
            batch_minutes=batch_minutes, max_batch_bars=max_batch_bars,
        )
        processed, batches, largest_batch = (replay[key] for key in
                                             ("bars", "batch_count", "max_batch_bars"))
        largest_event_batch = largest_batch
        timeline_first_ns = first_available_ns
        next_bar_open_orders = probe_strategy.submitted if probe_strategy is not None else 0
        expected_probe_fill_prices = probe_strategy.expected_fill_prices if probe_strategy is not None else []
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
            native_settlements=int(replay.get("settlements", 0)),
            source_inputs=tuple(replay.get("source_inputs", ())),
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

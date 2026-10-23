"""Synthetic, isolated NT fee-model benchmark; run with ``python -m``.

Example: python -m tests.benchmarks.bench_nautilus_historical_fees --bars 1000 --samples 5
This is an execution-path benchmark, not a T/TL production or browser p95.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import subprocess
import sys
import time
from decimal import Decimal

from server.services.nautilus_bridge.historical_fees import (
    FeeRuleAt,
    make_nautilus_fee_model,
)
from tests.server.test_nautilus_bridge_historical_rule_events import (
    _bars,
    _engine,
    _instrument,
    _nt,
)


def _run_one(case: str, bar_count: int) -> dict:
    nt = _nt()
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import BarType, OrderSide, Quantity, TimeInForce
    from nautilus_trader.trading import Strategy

    instrument = _instrument()
    bars = _bars(instrument, count=bar_count)

    class ClockRef:
        delegate = None

        def timestamp_ns(self):
            return self.delegate.timestamp_ns()

    class Probe(Strategy):
        def __new__(cls, *args, **kwargs):
            return super().__new__(cls)

        def __init__(self):
            super().__init__()
            self.bar_type = BarType.from_str(f"{instrument.id}-1-MINUTE-LAST-EXTERNAL")
            self.seen = 0
            self.fills = 0

        def on_start(self):
            self.subscribe_bars(self.bar_type)

        def on_bar(self, bar):
            self.seen += 1
            side = OrderSide.BUY if self.seen % 2 else OrderSide.SELL
            order = self.order_factory.market(
                instrument_id=instrument.id,
                order_side=side,
                quantity=Quantity.from_str("1"),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)

        def on_order_filled(self, event):
            self.fills += 1

    clock = ClockRef()
    if case == "built_in":
        fee = MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0))
    else:
        zero = (Decimal(0), Decimal(0))
        fee = make_nautilus_fee_model(
            (FeeRuleAt(bars[0].ts_event, Decimal(10000), (zero, zero, zero)),),
            clock=clock,
            classify_fill=lambda order, instrument: "open",
            currency="CNY",
        )
    started = time.perf_counter()
    engine = _engine(instrument, fee)
    probe = Probe()
    engine.add_strategy(probe)
    clock.delegate = probe.clock
    try:
        engine.add_data(bars)
        engine.run()
        result = engine.get_result()
        elapsed = time.perf_counter() - started
        raw_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "case": case,
            "bars": bar_count,
            "fills": probe.fills,
            "orders": result.total_orders,
            "elapsed_ms": round(elapsed * 1000, 3),
            "peak_rss_bytes": int(raw_rss * (1024 if sys.platform.startswith("linux") else 1)),
            "nt_version": nt.__version__,
        }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--case", choices=("built_in", "historical"))
    args = parser.parse_args()
    if not 10 <= args.bars <= 10_000 or not 1 <= args.samples <= 20:
        parser.error("bars must be 10..10000 and samples 1..20")
    if args.case:
        print("BENCH_JSON " + json.dumps(_run_one(args.case, args.bars), sort_keys=True))
        return

    samples = {case: [] for case in ("built_in", "historical")}
    for _ in range(args.samples + 1):
        for case, rows in samples.items():
            completed = subprocess.run(
                [sys.executable, "-m", __spec__.name, "--bars", str(args.bars),
                 "--case", case],
                check=True, capture_output=True, text=True,
            )
            row = next(line.removeprefix("BENCH_JSON ") for line in
                       completed.stdout.splitlines() if line.startswith("BENCH_JSON "))
            rows.append(json.loads(row))
    warm = {case: rows[1:] for case, rows in samples.items()}
    if len({row["fills"] for rows in warm.values() for row in rows}) != 1:
        raise RuntimeError("fee models produced different fill counts")
    summary = {
        "runtime": f"Python {platform.python_version()} / {platform.machine()}",
        "data": f"{args.bars} synthetic one-minute bars, one instrument, alternating market orders",
        "cache": "fresh NT engine and generated bars per isolated process; first sample discarded",
        "samples": args.samples,
        "cases": {
            case: {
                "fills": rows[0]["fills"],
                "median_ms": round(statistics.median(row["elapsed_ms"] for row in rows), 3),
                "median_peak_rss_bytes": int(statistics.median(
                    row["peak_rss_bytes"] for row in rows)),
                "min_ms": min(row["elapsed_ms"] for row in rows),
                "max_ms": max(row["elapsed_ms"] for row in rows),
            } for case, rows in warm.items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

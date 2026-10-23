"""Measure dense versus sparse synthetic historical-rule freezing.

Run in the NautilusTrader environment with ``python -m``. This benchmark
isolates one contract and tiny in-memory exchange notices; it does not measure
real source loading, multi-contract replay, or production p95.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import time
from datetime import date

import pandas as pd

from server.services.nautilus_bridge.historical_fees import (
    freeze_fee_schedule,
    freeze_fee_schedule_from_history,
)
from server.services.nautilus_bridge.trading_fields import (
    TradingFieldEvent,
    iter_trading_field_timeline,
)
from tests.server.test_nautilus_bridge_trading_fields import SOURCE, _provider, _rules


def _events(count: int):
    start = pd.Timestamp("2025-01-02 09:00:00")
    for index in range(count):
        yield TradingFieldEvent(
            start + pd.Timedelta(minutes=index), date(2025, 1, 2),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--mode", choices=("dense", "sparse"), default="sparse")
    args = parser.parse_args()
    if not 2 <= args.events <= 100_000 or not 1 <= args.samples <= 20:
        parser.error("events must be 2..100000 and samples 1..20")

    samples = []
    for _ in range(args.samples + 1):
        provider = _provider()
        started = time.perf_counter()
        if args.mode == "dense":
            schedule = freeze_fee_schedule(iter_trading_field_timeline(
                source=SOURCE, instrument="AU.SHFE", events=_events(args.events),
                provider=provider, rules=_rules(),
            ))
        else:
            schedule = freeze_fee_schedule_from_history(
                source=SOURCE, instrument="AU.SHFE", events=_events(args.events),
                provider=provider, rules=_rules(),
            )
        samples.append(time.perf_counter() - started)
        if len(schedule) != 2:
            raise RuntimeError("benchmark fee schedule changed")
    warm = samples[1:]
    print(json.dumps({
        "mode": args.mode,
        "events": args.events,
        "rules": len(schedule),
        "samples": args.samples,
        "median_ms": round(statistics.median(warm) * 1000, 3),
        "min_ms": round(min(warm) * 1000, 3),
        "max_ms": round(max(warm) * 1000, 3),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "runtime": f"Python {platform.python_version()} / {platform.machine()}",
        "cache": "fresh provider per sample; first sample discarded",
        "scope": "synthetic single-contract notices; generated minute event stream",
    }, sort_keys=True))


if __name__ == "__main__":
    main()

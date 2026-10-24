"""Measure staged Nautilus catalog conversion on local T/TL Parquet files.

Run with ``python -m tests.benchmarks.bench_nautilus_catalog_staging`` in the
NautilusTrader environment. Instrument values here are deliberately
performance-only placeholders; no execution result or metadata is validated.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from server.services.nautilus_bridge.catalog import stage_contract_minute_catalog
from server.services.nautilus_bridge.market_data import FuturesContractSpec
from tests.nautilus_source_fixture import resolved_contract_minute_source

DATA_ROOT = Path("/Users/maxdeux/Documents/GTHT/data/sources/LocalCNFutures/data_mink_product")


def _stage_one(code: str, month: str, batch: int) -> dict[str, object]:
    source = DATA_ROOT / f"CFFEX_F_{code}_{month}.parquet"
    spec = FuturesContractSpec(
        instrument_code=f"{code}{month}", venue="CFFEX", underlying=code,
        price_increment=Decimal("0.001"), price_precision=3,
        multiplier=Decimal(10000), currency="CNY",
        activation_ns=1,
        expiration_ns=2_000_000_000_000_000_000,
        margin_init=Decimal("0.02"), margin_maint=Decimal("0.02"),
        provenance="performance-only placeholder; not exchange metadata",
        resolved_source=resolved_contract_minute_source(),
    )
    with tempfile.TemporaryDirectory(prefix="ft-nt-catalog-bench-") as root:
        target = Path(root) / "catalog"
        started = time.perf_counter()
        receipt = stage_contract_minute_catalog(
            source, target, contract_uid=f"CFFEX|F|{code}|{month}",
            instrument_spec=spec, start_ns=0,
            end_ns=2_000_000_000_000_000_000,
            batch_bars=batch, max_bars=100_000,
        )
        return {
            "contract": f"{code}{month}",
            "source_bytes": source.stat().st_size,
            "bars": receipt.selected_count,
            "batches": (receipt.selected_count + batch - 1) // batch,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "peak_rss_bytes": receipt.process_peak_rss_bytes,
            "catalog_bytes": sum(int(item["bytes"]) for item in receipt.catalog_files),
            "source_sha256": receipt.source_sha256,
        }


def _worker(code: str, month: str, batch: int) -> None:
    print("BENCH_JSON " + json.dumps(_stage_one(code, month, batch), sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contracts", nargs="+", default=["T2403", "TL2406"])
    parser.add_argument("--batch-bars", type=int, default=4096)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--contract")
    args = parser.parse_args()
    if not 1 <= args.batch_bars <= 10_000 or not 1 <= args.samples <= 10:
        parser.error("batch-bars must be 1..10000 and samples 1..10")
    if args.contract:
        if len(args.contract) < 2 or not args.contract[:-4].isalpha():
            parser.error("contract must look like T2403 or TL2406")
        _worker(args.contract[:-4], args.contract[-4:], args.batch_bars)
        return

    outputs = {}
    for contract in args.contracts:
        if len(contract) < 2 or not contract[:-4].isalpha():
            parser.error(f"invalid contract {contract!r}")
        code, month = contract[:-4], contract[-4:]
        rows = []
        for _ in range(args.samples + 1):
            completed = subprocess.run(
                [sys.executable, "-m", __spec__.name,
                 "--contract", contract, "--batch-bars", str(args.batch_bars)],
                check=True, capture_output=True, text=True,
            )
            line = next(item for item in completed.stdout.splitlines()
                        if item.startswith("BENCH_JSON "))
            rows.append(json.loads(line.removeprefix("BENCH_JSON ")))
        warm = rows[1:]
        if len({(row["bars"], row["source_sha256"]) for row in warm}) != 1:
            raise RuntimeError("source contents changed between benchmark samples")
        outputs[f"{code}{month}"] = {
            "bars": warm[0]["bars"],
            "source_bytes": warm[0]["source_bytes"],
            "catalog_bytes": warm[0]["catalog_bytes"],
            "median_ms": round(statistics.median(row["elapsed_ms"] for row in warm), 3),
            "peak_rss_bytes": max(row["peak_rss_bytes"] for row in warm),
            "sample_count": args.samples,
        }
    print(json.dumps({
        "runtime": f"Python {platform.python_version()} / {platform.machine()}",
        "nautilus_version": "NautilusTrader 2.0.0rc7",
        "cache": "fresh process/catalog per sample; first sample discarded",
        "batch_bars": args.batch_bars,
        "metadata": "placeholder contract settings; performance only",
        "results": outputs,
    }, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

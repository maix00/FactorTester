"""Offline real T/TL acceptance: Python freezes inputs, then exits the data path.

The standalone Rust process owns Catalog replay, factors and bounded output.
This is not a production Job or an original-paper return reproduction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
import re
import statistics
import subprocess
import sys

import numpy as np
from alpha.factor import ColumnRef, ConstExpr, SignalAlign, WhereOp, to_plan_spec
from server.services.nautilus_bridge.backtest_runner import _load_input, ReplayInput
from tests.server.test_nautilus_bridge_backtest_runner import _real_catalog


def expected_rows(bars):
    """Independent positional mean/as-of/where/shift, never the tested kernel."""
    prices = np.asarray([float(bar.close) for bar in bars])
    times = np.asarray([int(bar.ts_event) for bar in bars], dtype=np.int64)
    mean = np.asarray([math.fsum(prices[max(0, i-19):i+1]) / min(20,i+1) for i in range(len(prices))])
    period = 300_000_000_000
    targets = times // period * period
    first_target = (int(times[0]) + period-1) // period * period
    positions = np.searchsorted(times, targets, side="right") - 1
    signal = np.where(targets >= first_target, prices[np.maximum(positions,0)], np.nan)
    return np.column_stack((mean, signal, np.where(signal > mean,1.0,0.0), np.r_[np.nan,mean[:-1]]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bars", type=int, default=500)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--catalog-input-dir", type=Path)
    args = parser.parse_args()
    if not 8 <= args.bars <= 2_000 or not 1 <= args.samples <= 5:
        parser.error("bars must be 8..2000 and samples 1..5")
    args.output_dir.mkdir(parents=True,exist_ok=False)
    close = ColumnRef("CLOSE")
    mean = close.rolling(20).semantics(min_periods=1).mean()
    signal = SignalAlign(close,"5min")
    plan = to_plan_spec([mean,signal,WhereOp(signal > mean,ConstExpr(1),ConstExpr(0)),mean.shift(1)],products=("T","TL"))
    if plan is None:
        raise RuntimeError("public factor API could not compile the acceptance plan")
    sources, expected, source_receipts = [], [], []
    reused = {} if args.catalog_input_dir is None else {
        product["product"]: product for product in json.loads((args.catalog_input_dir/"manifest.json").read_text())["products"]
    }
    times = available = None
    for code, month in (("T","2403"),("TL","2406")):
        folder = args.output_dir/code
        folder.mkdir()
        item = (ReplayInput(Path(reused[code]["catalog_path"]),f"CFFEX|F|{code}|{month}")
                if reused else _real_catalog(folder,code=code,month=month,count=args.bars))
        _, catalog, receipt, _ = _load_input(item)
        bars = catalog.query_bars(identifiers=[receipt["bar_type"]])
        if len(bars) != args.bars:
            raise RuntimeError("frozen catalog count differs from the acceptance workload")
        current_times = [int(bar.ts_event) for bar in bars]
        current_available = [int(bar.ts_init) for bar in bars]
        if times is not None and current_times != times:
            raise RuntimeError("acceptance fixture requires a shared dense clock")
        times = current_times
        available = current_available if available is None else np.maximum(available,current_available).tolist()
        expected.append(expected_rows(bars))
        sources.append({"product":code,"catalog_path":str(item.catalog_dir),"bar_type":receipt["bar_type"]})
        source_receipts.append(receipt)
    reference = np.stack(expected,axis=2).reshape(args.bars,-1)
    manifest = {"venue":"CFFEX","starting_balances":["1000000 CNY"],"products":sources,
                "fields":plan["columns"],"plan":plan,"chunk_size":40,"cache_bar_capacity":1,"expected_slices":args.bars}
    manifest_path = args.output_dir/"manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    (args.output_dir/"source-receipts.json").write_text(json.dumps(source_receipts))
    measurements = []
    for sample in range(args.samples+1):
        output = args.output_dir/f"updates-{sample}.jsonl"
        log, timing = args.output_dir/f"run-{sample}.log", args.output_dir/f"time-{sample}.log"
        command = ["/usr/bin/time", "-l" if sys.platform == "darwin" else "-v",
                   str(args.binary.resolve()),str(manifest_path.resolve()),str(output.resolve())]
        with log.open("w") as stdout, timing.open("w") as stderr:
            subprocess.run(command,stdout=stdout,stderr=stderr,check=True)
        count = 0
        with output.open() as rows:
            for row_index,line in enumerate(rows):
                row = json.loads(line)
                assert row["timestamp_ns"] == times[row_index]
                assert row["available_at_ns"] == available[row_index]
                np.testing.assert_allclose(np.asarray(row["values"],dtype=float),reference[row_index],
                    rtol=1e-11,atol=1e-10,equal_nan=True,err_msg=f"sample={sample} row={row_index} timestamp={times[row_index]}")
                count += 1
        assert count == args.bars
        result = next(json.loads(line.removeprefix("RESULT_JSON ")) for line in log.read_text().splitlines()
                      if line.startswith("RESULT_JSON "))
        time_text = timing.read_text()
        rss = (re.search(r"(\d+)\s+maximum resident set size",time_text) if sys.platform == "darwin"
               else re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)",time_text))
        if rss is None:
            raise RuntimeError("time did not report process RSS")
        result["peak_rss_bytes"] = int(rss.group(1)) * (1 if sys.platform == "darwin" else 1024)
        measurements.append(result)
    root = Path(__file__).resolve().parents[2]
    source_paths = ["vendor/py-alpha-lib/alpha-algo/src/algo/factor_plan.rs",
                    "vendor/py-alpha-lib/alpha-algo/src/algo/session_window.rs",
                    "native/nautilus_factor_bridge/src/lib.rs",
                    "native/nautilus_factor_bridge/src/replay.rs",
                    "native/nautilus_factor_bridge/examples/catalog_replay.rs",
                    "native/nautilus_factor_bridge/Cargo.lock"]
    summary = {"source_sha256":{path:hashlib.sha256((root/path).read_bytes()).hexdigest() for path in source_paths},
               "binary_sha256":hashlib.sha256(args.binary.read_bytes()).hexdigest(),
               "platform":platform.platform(),"python":sys.version.split()[0],"bars_per_product":args.bars,
               "products":2,"outputs":4,"plan_nodes":len(plan["nodes"]),"warmup":measurements[0],
               "samples":measurements[1:],"median_elapsed_s":statistics.median(row["elapsed_s"] for row in measurements[1:]),
               "max_peak_rss_bytes":max(row["peak_rss_bytes"] for row in measurements[1:]),
               "scope":"offline native runtime, excludes Python source staging; no Job/report/sync claim"}
    (args.output_dir/"measurements.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()

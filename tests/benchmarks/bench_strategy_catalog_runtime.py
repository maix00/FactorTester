"""Measure real frozen catalogs/family/reports using native catalog replay.

Run in a fresh GTHT process against an existing catalog_replay manifest.
This measures a local family runtime, not Celery, source conversion or deployment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import resource
import sys
import time

from server.services.nautilus_bridge import strategy_backtest
from server.services.nautilus_bridge.backtest_runner import (
    ReplayInput,
)
from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup
from tools.factors.expr import CLOSE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    inputs = {}
    for row in manifest["products"]:
        folder = Path(row["catalog_path"])
        receipt = json.loads((folder / "factor_tester_catalog_receipt.json").read_text())
        inputs[row["product"]] = ReplayInput(folder, receipt["contract_uid"])
    started = time.perf_counter()
    result = strategy_backtest.run_strategy_family_replay(
        inputs=inputs, factor_bindings={"signal": CLOSE.rolling(20).semantics(min_periods=1).mean()},
        factor_refs={"signal": "factor:v2:" + "a" * 43},
        family=CrossSectionalGroup(2, 1), output_dir=args.output_dir / "reports",
        max_bars=manifest["expected_slices"], batch_minutes=20,
    )
    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    summary = {"backend": "native", "platform": platform.platform(),
               "python": sys.version.split()[0], "elapsed_s": elapsed,
               "process_peak_rss_bytes": peak * (1024 if sys.platform.startswith("linux") else 1),
               "cache": "unchanged Nautilus engine defaults", "result": result,
               "scope": "local real family and reports with Rust FactorActor/native strategies; excludes source conversion/Celery"}
    (args.output_dir / "measurements.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

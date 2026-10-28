"""Export NautilusTrader's own post-run reports as bounded Job artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any

_REPORT_METHODS = {
    "orders.csv": "generate_orders_report",
    "fills.csv": "generate_fills_report",
    "positions.csv": "generate_positions_report",
}


def _record(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"name": path.name, "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def export_backtest_reports(
    engine: Any,
    destination: Path,
    *,
    venue: Any,
    max_artifact_bytes: int = 32 * 1024 * 1024,
    performance_window: dict | None = None,
) -> dict[str, object]:
    """Write a native tearsheet and reports after a completed backtest.

    The caller owns a fresh, private Job artifact directory and runs this
    function in an isolated worker with a hard memory limit.  The receipt is
    published with the artifacts: a partial export must never be presented
    as complete. ``venue`` is mandatory because NautilusTrader's account
    report requires a venue or account ID.
    This does not turn NautilusTrader's HTML into trusted Manager UI code.
    """
    if max_artifact_bytes <= 0:
        raise ValueError("max_artifact_bytes must be positive")
    if venue is None:
        raise ValueError("venue is required for account and margin history")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("Nautilus report destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    names = ["tearsheet.html", *_REPORT_METHODS, "account.csv"]

    # Lazily importing the optional visualization dependency keeps ordinary
    # Manager and business-port startup independent of pandas/Plotly.
    from nautilus_trader.analysis import create_tearsheet

    with tempfile.TemporaryDirectory(prefix=".nautilus-", dir=destination.parent) as raw:
        staging = Path(raw)
        html = staging / "tearsheet.html"
        if performance_window is None:
            create_tearsheet(engine=engine, output_path=str(html))
        else:
            _create_windowed_tearsheet(engine,html,performance_window)
        if not html.is_file() or html.stat().st_size == 0:
            raise RuntimeError("NautilusTrader did not produce a tearsheet")

        for name, method_name in _REPORT_METHODS.items():
            report = getattr(engine, method_name)()
            report.to_csv(staging / name)
        engine.generate_account_report(venue=venue).to_csv(staging / "account.csv")

        files = [staging / name for name in names]
        if any(not path.is_file() for path in files):
            raise RuntimeError("NautilusTrader did not produce all reports")
        if any(path.stat().st_size > max_artifact_bytes for path in files):
            raise ValueError("Nautilus report exceeds the per-artifact limit")
        receipt: dict[str, object] = {
            "engine": "nautilus_trader",
            "engine_version": metadata.version("nautilus_trader"),
            "performance_window": performance_window,
            "artifacts": [_record(path) for path in files],
        }
        receipt_path = staging / "nautilus_receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if receipt_path.stat().st_size > max_artifact_bytes:
            raise ValueError("Nautilus receipt exceeds the per-artifact limit")
        # A single directory rename keeps the receipt and its checksummed
        # files visible together to Job readers.
        os.replace(staging, destination)
        return receipt


def _create_windowed_tearsheet(engine,path,window):
    """Use Nautilus returns/statistics, restricted to the formal period.

    Raw CSVs remain complete audit records. The pinned native returns resolver
    is reused; no second finance calculator or replay is introduced.
    """
    import pandas as pd
    from nautilus_trader.analysis import create_tearsheet_from_stats
    import nautilus_trader.analysis as analysis
    from nautilus_trader.analysis.tearsheet import _resolve_tearsheet_returns
    result=engine.get_result();eligible=window['performance_eligible']
    returns=_resolve_tearsheet_returns(engine) if eligible else pd.Series(dtype=float)
    start=pd.Timestamp(window['performance_start_ns'],unit='ns',tz='UTC')
    end=pd.Timestamp(window['performance_end_ns'],unit='ns',tz='UTC')
    if not returns.empty:
        returns.index=pd.to_datetime(returns.index,utc=True)
        returns=returns.loc[(returns.index>=start.normalize()) & (returns.index<=end)]
    raw={int(t.value):float(value) for t,value in returns.items()}
    stats={}
    if eligible:
        for name in ("ReturnsVolatility","ReturnsSkewness","ReturnsKurtosis","ReturnsAverage","ReturnsAverageLoss","ReturnsAverageWin","SharpeRatio","SortinoRatio","TailRatio","ProfitFactor","RiskReturnRatio","MaxDrawdown"):
            statistic=getattr(analysis,name)()
            value=statistic.calculate_from_returns(raw)
            if value is not None:stats[statistic.name]=value
    create_tearsheet_from_stats(stats_pnls=dict(result.stats_pnls) if eligible else {},
        stats_returns=stats,stats_general=dict(result.stats_general) if eligible else {},
        returns=returns,output_path=str(path),engine=engine,
        title='NautilusTrader · formal performance' if eligible else 'Diagnostic only · warmup disabled · no formal performance',
        run_info={'Performance start':start.isoformat(),'Performance end':end.isoformat(),
                  'Warmup mode':window['settings']['mode'],'Performance eligible':str(eligible)})

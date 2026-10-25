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
        create_tearsheet(engine=engine, output_path=str(html))
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

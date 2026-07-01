"""Audit TransactionFee historical coverage.

The unified view intentionally merges official historical events with OpenCTP's
latest listed-contract baseline. This script reports where the current view is
still baseline-only, so the next data-cleaning pass can target official exchange
notices instead of guessing from the latest snapshot.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from sources.FieldHistory.views.TransactionFee import build_unified_frame


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit transaction-fee FieldHistory coverage")
    parser.add_argument("--output", default="", help="Optional CSV path for baseline-only rows")
    parser.add_argument("--limit", type=int, default=30, help="Number of baseline-only rows to print")
    args = parser.parse_args()

    frame = build_unified_frame()
    if frame.empty:
        print("TransactionFee unified view is empty")
        return 1

    frame = frame.copy()
    frame["is_agent"] = frame["providers"].map(lambda value: "Agent:" in str(value))
    frame["is_latest_only"] = frame["providers"].map(lambda value: str(value).strip() == '["OpenCTP:latest"]')
    summary = {
        "rows": int(len(frame)),
        "agent_rows": int(frame["is_agent"].sum()),
        "latest_only_rows": int(frame["is_latest_only"].sum()),
        "instruments": int(frame["instrument"].nunique()),
        "agent_instruments": int(frame.loc[frame["is_agent"], "instrument"].nunique()),
        "latest_only_instruments": int(frame.loc[frame["is_latest_only"], "instrument"].nunique()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\nby provider:")
    for item in _group_counts(frame, ["providers"]):
        print(item)

    print("\nagent coverage by notice:")
    agent = frame[frame["is_agent"]].copy()
    if agent.empty:
        print("(none)")
    else:
        for item in _group_counts(agent, ["source_notice_ids", "instrument"]):
            print(item)

    latest_only = frame[frame["is_latest_only"]].copy()
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        latest_only.to_csv(output, index=False)
        print(f"\nwrote baseline-only rows: {output}")

    print("\nbaseline-only sample:")
    cols = ["instrument", "instrument_label", "field_name", "value", "contract_codes", "source_notice_ids"]
    sample = latest_only.sort_values(["instrument", "contract_codes", "field_name"]).head(max(args.limit, 0))
    if sample.empty:
        print("(none)")
    else:
        print(sample[cols].to_string(index=False))
    return 0


def _group_counts(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    grouped = (
        frame.groupby(columns, dropna=False)
        .agg(rows=("field_name", "size"), instruments=("instrument", "nunique"))
        .reset_index()
        .sort_values(["rows", "instruments"], ascending=False)
    )
    return [dict(row) for _, row in grouped.iterrows()]


if __name__ == "__main__":
    raise SystemExit(main())

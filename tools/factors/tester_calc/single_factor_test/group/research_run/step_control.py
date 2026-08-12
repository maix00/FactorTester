"""Build the durable step-mode pause controller."""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_step_callback(payload: dict[str, Any], sink: Any):
    if not bool(payload.get("step_mode")):
        return None
    after_index = max(0, int(payload.get("step_after_index") or 0))
    raw_until = str(payload.get("step_until") or "").strip()
    cursor = {
        "flow_index": 0,
        "until": pd.Timestamp(raw_until).tz_localize(None) if raw_until else None,
        "run_to_end": False,
    }

    def should_capture(timestamp: Any) -> bool:
        cursor["flow_index"] += 1
        if cursor["run_to_end"] or cursor["flow_index"] <= after_index:
            return False
        if cursor["until"] is None:
            return True
        if timestamp is None:
            return False
        return pd.Timestamp(timestamp).tz_localize(None) >= cursor["until"]

    def checkpoint(info: dict[str, Any]) -> None:
        from tools.testers.backtest.engines.cancellation import BacktestCancelled

        checkpoint_payload = {**info, "flow_index": cursor["flow_index"]}
        sink.emit_step(checkpoint_payload)
        command = sink.emit_pause(checkpoint_payload) or {}
        action = str(command.get("action") or "continue")
        if action == "cancel":
            raise BacktestCancelled("group step job cancelled")
        if action == "end":
            cursor["run_to_end"] = True
            return
        raw_next_until = str(command.get("until") or "").strip()
        cursor["until"] = (
            pd.Timestamp(raw_next_until).tz_localize(None)
            if raw_next_until else None
        )

    setattr(checkpoint, "should_capture", should_capture)
    return checkpoint

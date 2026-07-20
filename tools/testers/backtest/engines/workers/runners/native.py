"""Native worker runner.

The native HTTP/server path uses the Event/Order/Flow scheduler directly.
The framework-worker contract tests still exercise the compact worker payload
shape, so this module delegates that payload to the framework-free reference
loop. That keeps parity checks alive without resurrecting the deleted
PhaseContext/StagePipeline runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def run_strategy_intents(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    from .reference import run_group_strategy as run_reference_group_strategy

    if progress is None:
        return run_reference_group_strategy(payload, progress=None, engine="native")

    timestamps = tuple(payload.get("timestamps", ()))
    bar_count = len(timestamps)

    def _progress(completed: int, total: int, timestamp: Any) -> None:
        if bar_count <= 0 or completed > bar_count:
            return
        progress(completed, bar_count, timestamp)

    return run_reference_group_strategy(payload, progress=_progress, engine="native")


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    return run_strategy_intents(payload, progress=progress)

"""Native event-driven runner — dispatches to the new Event/Order/Flow
scheduler (`tools.testers.backtest.engines.native.scheduler`).

`run_group_strategy`'s real body, plus `_build_pipeline`/the StagePipeline-
based wiring, was deleted as part of the issue-114 rewrite (old
`PhaseContext`/`StagePipeline`/`EventRuntime` no longer exist). Production
rewiring onto the new scheduler happens in step 11; until then this raises
clearly instead of silently doing nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def run_group_strategy(payload: Mapping[str, Any], progress=None) -> dict[str, Any]:
    """Run a group strategy backtest using the new Event/Order/Flow scheduler.

    Pending issue-114 step 11 production rewiring — the old
    PhaseContext/StagePipeline/EventRuntime-based implementation was removed
    in step 0 of the rewrite."""
    raise NotImplementedError(
        "run_group_strategy: pending issue-114 step 11 production rewiring "
        "onto the new Event/Order/Flow scheduler")

"""Emit retained order audit data through the durable job sink."""

from __future__ import annotations

from .projection import project_strategy_order_audit


def emit_order_audit_artifact(sink, state, run_id: str) -> None:
    if getattr(sink, "retention_mode", "full") != "full":
        return
    sink.emit_artifact("order_audit", {
        "run_id": run_id,
        "strategies": {
            str(getattr(strategy, "alias", strategy)): project_strategy_order_audit(
                state, strategy,
            )
            for strategy in state.strategy_configs
        },
    })

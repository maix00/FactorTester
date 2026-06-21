"""Choose precomputed or incremental factor actors for an event-driven run."""

from __future__ import annotations

from enum import Enum

from tools.factors.expr import FactorExpr

from .incremental import UnsupportedStreamingFactor, compile_streaming_factor


class FactorMode(str, Enum):
    AUTO = "auto"
    PRECOMPUTED = "precomputed"
    INCREMENTAL = "incremental"


def select_factor_mode(
    requested: str,
    expression: FactorExpr,
    products: tuple[str, ...],
) -> FactorMode:
    """Select computation only; both modes still publish factor events."""
    mode = FactorMode(requested)
    if mode == FactorMode.PRECOMPUTED:
        return mode
    try:
        compile_streaming_factor(expression, products)
    except UnsupportedStreamingFactor:
        if mode == FactorMode.INCREMENTAL:
            raise
        return FactorMode.PRECOMPUTED
    return FactorMode.INCREMENTAL

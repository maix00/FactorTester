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
    """Select computation only; auto prefers vectorized precomputation."""
    mode = FactorMode(requested)
    if mode == FactorMode.PRECOMPUTED:
        if not expression.supports_vectorized():
            raise UnsupportedStreamingFactor("precomputed mode requires a vectorizable factor")
        return mode
    if mode == FactorMode.AUTO and expression.supports_vectorized():
        return FactorMode.PRECOMPUTED
    if not expression.supports_incremental():
        raise UnsupportedStreamingFactor("factor does not support incremental execution")
    compile_streaming_factor(expression, products)
    return FactorMode.INCREMENTAL

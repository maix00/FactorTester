"""Bounded incremental execution for canonical FactorExpr expressions."""

from .incremental import (
    IncrementalFactorExecutor,
    UnsupportedStreamingFactor,
    compile_incremental_factor,
    compile_streaming_factor,
)

__all__ = [
    "IncrementalFactorExecutor",
    "UnsupportedStreamingFactor",
    "compile_incremental_factor",
    "compile_streaming_factor",
]

"""Bounded incremental execution for canonical FactorExpr expressions."""

from .incremental import (
    MultiStreamingIncrementalExecutor,
    SingleFactorIncrementalExecutor,
    UnsupportedStreamingFactor,
    compile_incremental_factor,
    compile_incremental_factors,
    compile_streaming_factor,
)

__all__ = [
    "MultiStreamingIncrementalExecutor",
    "SingleFactorIncrementalExecutor",
    "UnsupportedStreamingFactor",
    "compile_incremental_factor",
    "compile_incremental_factors",
    "compile_streaming_factor",
]

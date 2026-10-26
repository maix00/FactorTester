"""Bounded incremental execution for canonical FactorExpr expressions."""

from .incremental import (
    SingleFactorIncrementalExecutor,
    UnsupportedStreamingFactor,
    compile_incremental_factor,
    compile_incremental_factors,
)

__all__ = [
    "SingleFactorIncrementalExecutor",
    "UnsupportedStreamingFactor",
    "compile_incremental_factor",
    "compile_incremental_factors",
]

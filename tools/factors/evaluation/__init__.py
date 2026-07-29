"""Run-scoped batch evaluation helpers for factor expression graphs."""

from .batch import EvaluationBatchContext, evaluate_factors

__all__ = ["EvaluationBatchContext", "evaluate_factors"]

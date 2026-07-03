"""Analytics registries shared by reports, CLI, and backtest result modules."""

from .result_metrics import (
    ResultMetric,
    ResultMetricContext,
    compute_result_metrics,
    register_result_metric,
    registered_result_metrics,
    unregister_result_metric,
)

__all__ = [
    "ResultMetric",
    "ResultMetricContext",
    "compute_result_metrics",
    "register_result_metric",
    "registered_result_metrics",
    "unregister_result_metric",
]

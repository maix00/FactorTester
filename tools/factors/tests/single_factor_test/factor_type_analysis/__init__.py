"""
因子类型分析 — 包入口。

导出主要 API 类供外部使用。
"""

from .core import FactorTypeAnalyzer
from .registry import ReferenceFactorRegistry, ReferenceFactorDef, FactorCategory, default_registry
from .correlation import (
    compute_time_series_correlation,
    compute_product_correlation_matrix,
    categorize_correlation_strength,
    best_category_match,
)
from .server_facade import FactorTypeAnalysisRun

__all__ = [
    "FactorTypeAnalyzer",
    "ReferenceFactorRegistry",
    "ReferenceFactorDef",
    "FactorCategory",
    "default_registry",
    "compute_time_series_correlation",
    "compute_product_correlation_matrix",
    "categorize_correlation_strength",
    "best_category_match",
    "FactorTypeAnalysisRun",
]

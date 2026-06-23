"""
core — FactorTypeAnalyzer 主分析器。

协调参照因子注册 + 相关性计算 + 结果聚合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .correlation import (
    best_category_match,
    compute_product_correlation_matrix,
    compute_time_series_correlation,
    product_category_profiles,
)
from .registry import FactorCategory, ReferenceFactorRegistry, create_default_registry


@dataclass(slots=True)
class FactorTypeAnalysisResult:
    """因子类型分析的完整结果。"""

    # 与参照因子的逐对相关性
    reference_correlations: dict[str, dict[str, Any]] = field(default_factory=dict)

    # 按类别聚合的平均相关性
    category_correlations: dict[str, float] = field(default_factory=dict)

    # 最佳匹配类别
    best_match: dict[str, Any] = field(default_factory=dict)

    # 品种相关性矩阵
    product_correlation: dict[str, Any] = field(default_factory=dict)

    # 每个产品与参照类型的画像
    product_type_profiles: list[dict[str, Any]] = field(default_factory=list)

    # 每个因子类型下最相关的产品排名
    category_product_rankings: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # 元信息
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_correlations": {
                k: dict(v) for k, v in self.reference_correlations.items()
            },
            "category_correlations": dict(self.category_correlations),
            "best_match": dict(self.best_match),
            "product_correlation": dict(self.product_correlation),
            "product_type_profiles": [dict(item) for item in self.product_type_profiles],
            "category_product_rankings": {
                key: [dict(item) for item in value]
                for key, value in self.category_product_rankings.items()
            },
            "meta": dict(self.meta),
        }


class FactorTypeAnalyzer:
    """
    因子类型分析器。

    用法:
        analyzer = FactorTypeAnalyzer(registry=default_registry)
        result = analyzer.analyze(
            target_series={product: pd.Series},
            factor_name="MyFactor",
            method="pearson",
        )
    """

    def __init__(
        self,
        registry: ReferenceFactorRegistry | None = None,
    ):
        self._registry = registry or create_default_registry()

    @property
    def registry(self) -> ReferenceFactorRegistry:
        return self._registry

    def analyze(
        self,
        target_series: dict[str, pd.Series],
        factor_name: str = "",
        *,
        method: str = "pearson",
        min_periods: int = 30,
        reference_series: dict[str, pd.Series] | None = None,
    ) -> FactorTypeAnalysisResult:
        """
        执行因子类型分析。

        Args:
            target_series: {product: pd.Series} — 待测因子在各产品上的时序
            factor_name: 因子名称（用于元信息）
            method: "pearson" | "spearman"
            min_periods: 最少有效周期
            reference_series: 如果为 None，自动用 registry 中的算

        Returns:
            FactorTypeAnalysisResult
        """
        if reference_series is None:
            reference_series = self._evaluate_reference_series(target_series)

        # ----------------------------------------
        # 1) 取最长序列产品做整体摘要；同时保留逐产品画像。
        # ----------------------------------------
        products = list(target_series.keys())
        if not products:
            return FactorTypeAnalysisResult(
                meta={"factor_name": factor_name, "error": "no product data"}
            )

        # 选最长序列的产品作为代表性序列
        rep_product = max(
            products,
            key=lambda p: target_series[p].dropna().count(),
        )
        rep_series = target_series[rep_product]

        # 对参照因子逐个计算相关性
        ref_corrs = compute_time_series_correlation(
            target_series=rep_series,
            reference_series=reference_series,
            min_periods=min_periods,
            method=method,
        )
        self._sanity_check_ref_corrs(ref_corrs)

        # ----------------------------------------
        # 2) 按因子类别聚合
        # ----------------------------------------
        cat_corrs = self._aggregate_by_category(ref_corrs)

        # ----------------------------------------
        # 3) 最佳匹配类别
        # ----------------------------------------
        best = best_category_match(cat_corrs)

        # ----------------------------------------
        # 4) 品种相关性矩阵
        # ----------------------------------------
        prod_corr = compute_product_correlation_matrix(
            target_series,
            min_periods=min_periods,
            method=method,
        )
        profile_payload = product_category_profiles(
            target_series=target_series,
            reference_series=reference_series,
            registry=self._registry,
            min_periods=min_periods,
            method=method,
        )

        return FactorTypeAnalysisResult(
            reference_correlations=ref_corrs,
            category_correlations=cat_corrs,
            best_match=best,
            product_correlation=prod_corr,
            product_type_profiles=profile_payload["profiles"],
            category_product_rankings=profile_payload["category_rankings"],
            meta={
                "factor_name": factor_name,
                "representative_product": rep_product,
                "method": method,
                "min_periods": min_periods,
                "product_count": len(products),
                "reference_count": len(reference_series),
            },
        )

    def _evaluate_reference_series(
        self,
        target_series: dict[str, pd.Series],
    ) -> dict[str, pd.Series]:
        """
        解析参照因子的因子值序列。

        子类可重写此方法以实现更复杂的加载逻辑。
        当前简化为：参照因子由外部提供或通过 registry 配置加载。
        
        此方法在基类中直接返回空字典——实际参照因子序列
        由调用者提供（在 Server 层加载）。
        """
        return {}

    def _aggregate_by_category(
        self,
        ref_corrs: dict[str, dict[str, Any]],
    ) -> dict[str, float]:
        """按因子类别聚合平均相关性（按绝对值平均）。"""
        cat_values: dict[str, list[float]] = {}
        for ref_key, corr_info in ref_corrs.items():
            corr = corr_info.get("correlation")
            if corr is None:
                continue
            # 查找该参照因子的类别
            try:
                ref_def = self._registry.get(ref_key)
            except KeyError:
                continue
            cat_label = ref_def.category.label_cn
            cat_values.setdefault(cat_label, []).append(corr)

        return {
            cat: round(float(np.mean(values)), 4)
            for cat, values in cat_values.items()
            if values
        }

    def _sanity_check_ref_corrs(
        self,
        ref_corrs: dict[str, dict[str, Any]],
    ) -> None:
        """检查参照因子相关性是否有异常（全部为 None 等）。"""
        valid = sum(
            1 for v in ref_corrs.values() if v.get("correlation") is not None
        )
        if valid == 0:
            import warnings
            warnings.warn(
                "所有参照因子相关性计算均为 None，"
                "请检查因子数据是否有足够的有效周期。"
            )

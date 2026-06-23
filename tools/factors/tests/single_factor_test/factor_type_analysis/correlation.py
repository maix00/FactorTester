"""
correlation — 相关性计算模块。

提供时序相关性和品种相关性矩阵计算。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def compute_time_series_correlation(
    target_series: pd.Series,
    reference_series: dict[str, pd.Series],
    *,
    min_periods: int = 30,
    method: str = "pearson",
) -> dict[str, dict[str, Any]]:
    """
    计算待测因子序列与参照因子序列之间的时序相关性。

    Args:
        target_series: 待测因子时序（index 为时间，value 为因子值）
        reference_series: 参照因子序列字典 {name: pd.Series}
        min_periods: 最少有效期数（NaN 容忍）
        method: "pearson" | "spearman"

    Returns:
        {ref_name: {"correlation": float, "p_value": float, "valid_periods": int}}
    """
    results: dict[str, dict[str, Any]] = {}
    for ref_name, ref_series in reference_series.items():
        # 对齐时间轴
        aligned = pd.concat([target_series, ref_series], axis=1, join="inner")
        aligned.columns = ["target", "reference"]
        aligned = aligned.dropna()
        valid = len(aligned)

        if valid < min_periods:
            results[ref_name] = {
                "correlation": None,
                "p_value": None,
                "valid_periods": valid,
                "insufficient_data": True,
            }
            continue

        if method == "pearson":
            corr_matrix = aligned.corr(method="pearson")
            corr = corr_matrix.loc["target", "reference"]

            # 用 scipy 算 p_value
            from scipy import stats

            _, p_value = stats.pearsonr(aligned["target"], aligned["reference"])
        elif method == "spearman":
            corr_matrix = aligned.corr(method="spearman")
            corr = corr_matrix.loc["target", "reference"]

            from scipy import stats

            _, p_value = stats.spearmanr(aligned["target"], aligned["reference"])
        else:
            raise ValueError(f"unsupported correlation method: {method}")

        results[ref_name] = {
            "correlation": round(float(corr), 4) if not np.isnan(corr) else None,
            "p_value": round(float(p_value), 6) if not np.isnan(p_value) else None,
            "valid_periods": valid,
            "insufficient_data": False,
        }

    return results


def compute_product_correlation_matrix(
    factor_series: dict[str, pd.Series],
    *,
    min_periods: int = 30,
    method: str = "pearson",
) -> dict[str, Any]:
    """
    计算同一因子在不同产品上的因子值两两相关性矩阵。

    Args:
        factor_series: {product: pd.Series} — 各产品对该因子的时序
        min_periods: 最少有效期数
        method: "pearson" | "spearman"

    Returns:
        {
            "matrix": [[corr, ...], ...],
            "products": [product, ...],
            "p_values": [[p, ...], ...],
            "valid_pairs": int,
        }
    """
    if len(factor_series) < 2:
        return {
            "matrix": [],
            "products": list(factor_series.keys()),
            "p_values": [],
            "valid_pairs": 0,
        }

    # 对齐所有产品到统一时间轴
    aligned = pd.DataFrame(factor_series)
    aligned = aligned.dropna(how="any", axis=0)
    valid_count = len(aligned)

    if valid_count < min_periods:
        return {
            "matrix": [],
            "products": list(factor_series.keys()),
            "p_values": [],
            "valid_pairs": 0,
            "insufficient_data": True,
        }

    if method == "pearson":
        corr_matrix = aligned.corr(method="pearson")
    elif method == "spearman":
        corr_matrix = aligned.corr(method="spearman")
    else:
        raise ValueError(f"unsupported correlation method: {method}")

    # 转成嵌套列表 + p_value
    products = list(factor_series.keys())
    n = len(products)
    matrix = [[0.0] * n for _ in range(n)]
    p_matrix = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            val = corr_matrix.iloc[i, j]
            matrix[i][j] = round(float(val), 4) if not np.isnan(val) else None
            p_matrix[i][j] = None  # 多品种时使用中，省略 p_value

    return {
        "matrix": matrix,
        "products": products,
        "valid_periods": valid_count,
        "valid_pairs": len(factor_series),
        "insufficient_data": False,
    }


def categorize_correlation_strength(corr: float | None) -> str:
    """将相关系数映射为文字描述。"""
    if corr is None:
        return "无数据"
    abs_corr = abs(corr)
    if abs_corr >= 0.8:
        return "高度相关"
    elif abs_corr >= 0.5:
        return "中度相关"
    elif abs_corr >= 0.3:
        return "弱相关"
    else:
        return "几乎无关"


def best_category_match(
    category_correlations: dict[str, float],
) -> dict[str, Any]:
    """
    根据类别-相关性映射，判断最匹配的因子类别。

    Args:
        category_correlations: {category_label: avg_correlation}

    Returns:
        {"best_category": str, "best_corr": float, "all_categories": {str: float}}
    """
    if not category_correlations:
        return {"best_category": "", "best_corr": 0, "all_categories": {}}

    best_cat = max(category_correlations, key=lambda k: abs(category_correlations[k]))
    return {
        "best_category": best_cat,
        "best_corr": round(float(category_correlations[best_cat]), 4),
        "all_categories": {
            k: round(float(v), 4) for k, v in category_correlations.items()
        },
    }

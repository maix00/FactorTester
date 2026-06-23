"""
server_facade — Server 端的因子类型分析实现。

负责：
  1. 接收前端请求（因子选择 + 产品选择 + 时间范围）
  2. 创建 FactorTester 并计算目标因子 + 参照因子的序列
  3. 委派给 FactorTypeAnalyzer 做相关性分析
  4. 返回结构化的分析结果
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from server.modules.shared.factor_data_helpers import (
    clip_series_by_tester_range,
    find_factor as _find_factor,
    match_product_column as _match_product_column,
)
from server.modules.shared.factor_tester_runtime import create_factor_tester_for_run
from server.modules.shared.submission_model import ProductPathSelection
from server.services.factor_registry import get_factor_family_instance
from server.services.session_runtime import current_user_obj, get_session_params
from tools.data.types import DataTime, finest_index
from tools.factors.FactorTester import _active_tester
from tools.factors.tests.single_factor_test.factor_type_analysis import (
    FactorTypeAnalyzer,
    default_registry,
)
from tools.factors.tests.single_factor_test.factor_type_analysis.correlation import (
    compute_time_series_correlation,
    compute_product_correlation_matrix,
)


def _product_series_from_tester(
    tester,
    factor_alias: str,
) -> dict[str, pd.Series]:
    """
    从 FactorTester 中提取某因子在所有产品上的序列。

    Returns:
        {product_name: pd.Series}
    """
    factors = getattr(tester, "_factors", [])
    factor = next((f for f in factors if f.alias == factor_alias), None)
    if factor is None:
        # 尝试通过已计算的结果查找
        for f in getattr(tester, "_factors", []):
            result = tester.results.get(f)
            if result is not None:
                table = (
                    result.func_table if not result.func_table.empty
                    else result.table if not result.table.empty
                    else None
                )
                if table is not None:
                    break
        return {}

    result = tester.results.get(factor)
    if result is None:
        return {}

    table = (
        result.func_table if not result.func_table.empty
        else result.table if not result.table.empty
        else pd.DataFrame()
    )
    if table.empty:
        return {}

    series_by_product: dict[str, pd.Series] = {}
    for product in tester.products:
        name = str(getattr(product, "name", product))
        col = _match_product_column(table, product)
        if col is None:
            continue
        series = table[col].dropna()
        if series.empty:
            continue
        series = clip_series_by_tester_range(series, tester)
        series_by_product[name] = series

    return series_by_product


def _load_and_calc_factor(
    tester,
    factor_family_alias: str,
    factor_alias: str,
    page_uuid: str,
) -> Any:
    """
    加载因子族 → 获取因子定义 → 在 tester 上计算因子。
    返回计算后的 factor 对象。
    """
    factor_family = get_factor_family_instance(
        factor_family_alias,
        page_uuid=page_uuid,
    )
    factors = factor_family.get_factors(
        params_list=get_session_params(factor_family_alias, factor_family),
        page_uuid=page_uuid,
    )
    factor = _find_factor(factors, factor_alias, factor_alias)
    if factor is None:
        raise LookupError(f"因子 {factor_alias} 未找到，请先在配置中提交")

    token = _active_tester.set(tester)
    try:
        tester.calc_factor(factor, parallel=False)
    finally:
        _active_tester.reset(token)

    return factor


def _run_window_datetimes(
    settings: dict[str, Any] | None,
) -> tuple[DataTime | None, DataTime | None]:
    """从 settings 中解析时间范围。"""
    if not settings:
        return None, None
    start_date = str(settings.get("start_date") or "").strip()
    end_date = str(settings.get("end_date") or "").strip()
    if not start_date or not end_date:
        return None, None
    timezone = str(settings.get("timezone") or "Asia/Shanghai")
    start = pd.Timestamp(f"{start_date} 00:00").tz_localize(timezone)
    end = pd.Timestamp(f"{end_date} 23:59").tz_localize(timezone)
    return DataTime(ts=start), DataTime(ts=end)


@dataclass(slots=True)
class FactorTypeAnalysisRun:
    """一次因子类型分析的运行上下文。"""

    selection: ProductPathSelection
    factor_family_alias: str
    factor_alias: str
    page_uuid: str
    settings: dict[str, Any] | None = None
    method: str = "pearson"

    @classmethod
    def from_request(cls, data: dict[str, Any], *, page_uuid: str) -> "FactorTypeAnalysisRun":
        paths = data.get("paths") or data.get("selected_paths") or []
        if not isinstance(paths, list) or not paths:
            raise ValueError("请先从产品树选择产品或路径")
        factor_family_alias = str(data.get("factor_family_alias") or "").strip()
        factor_alias = str(data.get("factor_alias") or data.get("factor_name") or "").strip()
        if not factor_family_alias or not factor_alias:
            raise ValueError("请先选择因子")
        method = str(data.get("method") or "pearson").strip()
        if method not in ("pearson", "spearman"):
            method = "pearson"
        selection = ProductPathSelection.from_paths(
            "factor-type-analysis",
            paths,
            label="因子类型分析",
            source_type="factor_type_analysis",
            page_uuid=page_uuid,
        )
        return cls(
            selection=selection,
            factor_family_alias=factor_family_alias,
            factor_alias=factor_alias,
            page_uuid=page_uuid,
            settings=data.get("settings") if isinstance(data.get("settings"), dict) else None,
            method=method,
        )

    def run(self) -> dict[str, Any]:
        started_at = time.time()
        start_dt, end_dt = _run_window_datetimes(self.settings)

        # 1) 创建 FactorTester
        tester = create_factor_tester_for_run(
            self.selection,
            page_uuid=self.page_uuid,
            start_dt=start_dt,
            end_dt=end_dt,
            user=current_user_obj(),
        )

        # 2) 计算目标因子
        target_factor = _load_and_calc_factor(
            tester,
            self.factor_family_alias,
            self.factor_alias,
            self.page_uuid,
        )

        # 3) 提取目标因子在各产品上的序列
        target_series = _product_series_from_tester(tester, self.factor_alias)
        if not target_series:
            raise LookupError("目标因子没有可用的序列数据")

        # 4) 计算参照因子序列 — 需要先 calc 参照因子
        reference_series: dict[str, pd.Series] = {}
        for ref_def in default_registry.list():
            try:
                ref_factor = _load_and_calc_factor(
                    tester,
                    ref_def.factor_family_alias or self.factor_family_alias,
                    ref_def.factor_alias,
                    self.page_uuid,
                )
                ref_series = _product_series_from_tester(
                    tester, ref_def.factor_alias
                )
                if ref_series:
                    # 取与目标因子代表性产品相同的产品
                    rep_product = max(
                        target_series,
                        key=lambda p: target_series[p].dropna().count(),
                    )
                    if rep_product in ref_series:
                        reference_series[ref_def.key] = ref_series[rep_product]
                    else:
                        # 用第一个可用的
                        first = next(iter(ref_series.values()))
                        reference_series[ref_def.key] = first
            except Exception:
                # 单个参照因子失败不应中断整体
                continue

        # 5) 执行分析
        analyzer = FactorTypeAnalyzer(registry=default_registry)
        result = analyzer.analyze(
            target_series=target_series,
            factor_name=self.factor_alias,
            method=self.method,
            reference_series=reference_series,
        )

        # 6) 补充参照因子的元信息
        ref_details = []
        for ref_key, corr_info in result.reference_correlations.items():
            try:
                ref_def = default_registry.get(ref_key)
                ref_details.append({
                    "key": ref_def.key,
                    "name": ref_def.name,
                    "category": ref_def.category.value,
                    "category_label": ref_def.category.label_cn,
                    "correlation": corr_info.get("correlation"),
                    "p_value": corr_info.get("p_value"),
                    "valid_periods": corr_info.get("valid_periods", 0),
                    "insufficient_data": corr_info.get("insufficient_data", False),
                })
            except KeyError:
                pass

        # 7) 把原始时序也返回（方便前端展示）
        # 只返回产品层面的数据摘要，避免数据量过大
        product_summaries = []
        for prod_name, series in target_series.items():
            product_summaries.append({
                "product": prod_name,
                "count": int(series.dropna().count()),
                "start": str(series.index[0]) if len(series) else "",
                "end": str(series.index[-1]) if len(series) else "",
                "mean": round(float(series.mean()), 6) if len(series) else None,
                "std": round(float(series.std()), 6) if len(series) else None,
            })

        return {
            "success": True,
            "target_factor": {
                "alias": self.factor_alias,
                "family_alias": self.factor_family_alias,
            },
            "reference_factors": ref_details,
            "category_correlations": result.category_correlations,
            "best_match": result.best_match,
            "product_correlation": result.product_correlation,
            "product_summaries": product_summaries,
            "meta": {
                "elapsed_ms": round((time.time() - started_at) * 1000),
                "method": self.method,
                "product_count": len(target_series),
                "reference_count": len(reference_series),
            },
        }

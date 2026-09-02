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

from server.modules.factors.helpers import (
    clip_series_by_tester_range,
    find_factor as _find_factor,
    match_product_column as _match_product_column,
)
from server.modules.shared.factor_tester_runtime import create_factor_tester_for_run
from server.modules.shared.factor_tester_runtime import create_isolated_factor_tester_for_run
from server.modules.shared.factor_tester_runtime import selection_from_request
from server.modules.shared.factor_tester_runtime import require_run_window
from server.modules.shared.factor_data_coverage import require_factor_data_coverage
from tools.products.product_path_selection import ProductPathSelection
from server.services.factor_registry import factor_from_alias, get_factor_family_instance, get_page_factor, page_factors
from server.services.session_runtime import current_user_obj, user_obj_for_name
from tools.data.types import DataTime, finest_index
from tools.factors.FactorTester import _active_tester
from tools.factors.tester_calc.single_factor_test.factor_type_analysis import (
    FactorTypeAnalyzer,
    default_registry,
)
from tools.factors.tester_calc.single_factor_test.factor_type_analysis.correlation import (
    compute_time_series_correlation,
    compute_product_correlation_matrix,
)


def _product_series_from_tester(
    tester,
    factor_or_alias: Any,
) -> dict[str, pd.Series]:
    """
    从 FactorTester 中提取某因子在所有产品上的序列。

    Returns:
        {product_name: pd.Series}
    """
    factors = getattr(tester, "_factors", [])
    result = tester.results.get(factor_or_alias)
    factor = factor_or_alias if result is not None else None
    factor_alias = str(getattr(factor_or_alias, "alias", factor_or_alias))
    if factor is None:
        factor = next((f for f in factors if getattr(f, "alias", None) == factor_alias), None)
    if factor is None:
        factor = next((f for f in factors if str(getattr(f, "alias", "")) == factor_alias), None)
    if factor is None:
        # Last resort for older FactorTester result stores keyed by factor objects
        # that are not present in _factors.
        for f in getattr(tester, "_factors", []):
            result = tester.results.get(f)
            if result is not None:
                factor = f
                break
    if factor is None:
        return {}

    result = result or tester.results.get(factor)
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
    *,
    allow_default_factor: bool = False,
    owner: str = "",
    isolated: bool = False,
    external_factor_artifacts: list[dict[str, Any]] | None = None,
) -> Any:
    """
    加载因子族 → 获取因子定义 → 在 tester 上计算因子。
    返回计算后的 factor 对象。
    """
    if isolated:
        from server.services.external_factor_artifacts import factor_by_alias

        factor = factor_by_alias(
            external_factor_artifacts, factor_alias,
        ) or factor_from_alias(factor_alias, username=owner)
        token = _active_tester.set(tester)
        try:
            tester.calc_factor(factor, parallel=False)
        finally:
            _active_tester.reset(token)
        return factor

    factor_family = get_factor_family_instance(factor_family_alias, page_uuid=page_uuid)
    # Populate factor_family.factors from page_factors (single source of truth)
    from server.services.factor_registry import page_factors
    page_dict = page_factors.get(str(page_uuid), {})
    family_alias = getattr(factor_family, 'alias', factor_family_alias)
    factors = [
        f for alias, f in page_dict.items()
        if getattr(getattr(f, 'family', None), 'alias', None) == family_alias
    ]
    factor_family.factors = factors
    factor = _find_factor(factors, factor_alias, factor_alias)
    if factor is None and allow_default_factor:
        try:
            generated = factor_family.get_factors(page_uuid=page_uuid)
            factors = list(getattr(factor_family, "factors", []) or [])
            factor = _find_factor(factors, factor_alias, factor_alias)
            if factor is None and factor_alias == str(getattr(factor_family, "alias", factor_family_alias)):
                if isinstance(generated, list) and generated:
                    factor = generated[0]
                elif generated is not None and not isinstance(generated, list):
                    factor = generated
                elif factors:
                    factor = factors[0]
        except Exception:
            factor = None
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
) -> tuple[DataTime, DataTime]:
    """从 settings 中解析时间范围。"""
    if not settings:
        return require_run_window(None, None)
    start_date = str(settings.get("start_date") or "").strip()
    end_date = str(settings.get("end_date") or "").strip()
    if not start_date or not end_date:
        return require_run_window(start_date or None, end_date or None)
    precision = str(settings.get("time_precision") or "exact")
    if precision == "trading_day":
        return require_run_window(
            DataTime(ts=pd.Timestamp(start_date), precision="trading_day"),
            DataTime(ts=pd.Timestamp(end_date), precision="trading_day"),
        )
    timezone = str(settings.get("timezone") or "Asia/Shanghai")
    start_time = str(settings.get("start_time") or "00:00")
    end_time = str(settings.get("end_time") or "23:59")
    start = pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone)
    end = pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone)
    return require_run_window(
        DataTime(ts=start, precision="exact"),
        DataTime(ts=end, precision="exact"),
    )


def _infer_asset_classes(selection: ProductPathSelection) -> tuple[str, ...]:
    """Infer the broad asset domain from the selected product paths."""
    classes: set[str] = set()
    for raw_path in getattr(selection, "selected_paths", []) or []:
        path = str(raw_path).lstrip("-")
        lowered = path.lower()
        if "/futures/" in lowered or "cnfutures" in lowered or lowered.startswith("product/futures"):
            classes.add("futures")
        elif "/equity/" in lowered or "/stock" in lowered or lowered.startswith("product/equity"):
            classes.add("equity")
    return tuple(sorted(classes)) or ("unknown",)


def _reference_skip_reason(ref_def: Any, asset_classes: tuple[str, ...]) -> str | None:
    ref_assets = set(getattr(ref_def, "asset_classes", ()) or ())
    inferred_assets = set(asset_classes)
    if ref_assets and "unknown" not in inferred_assets and ref_assets.isdisjoint(inferred_assets):
        return "asset_class_not_applicable"
    if not getattr(ref_def, "enabled_by_default", True):
        required = ",".join(getattr(ref_def, "requires_data", ()) or ())
        return f"requires_explicit_enable_or_data:{required}" if required else "requires_explicit_enable"
    return None


@dataclass(slots=True)
class FactorTypeAnalysisRun:
    """一次因子类型分析的运行上下文。"""

    selection: ProductPathSelection
    factor_family_alias: str
    factor_alias: str
    page_uuid: str
    settings: dict[str, Any] | None = None
    method: str = "pearson"
    min_periods: int = 30
    owner: str = ""
    run_id: str = ""
    isolated: bool = False
    external_factor_artifacts: list[dict[str, Any]] | None = None

    @classmethod
    def from_request(cls, data: dict[str, Any], *, page_uuid: str) -> "FactorTypeAnalysisRun":
        factor_family_alias = str(data.get("factor_family_alias") or "").strip()
        factor_alias = str(data.get("factor_alias") or data.get("factor_name") or "").strip()
        if not factor_family_alias or not factor_alias:
            raise ValueError("请先选择因子")
        raw_settings = data.get("settings")
        settings: dict[str, Any] = (
            raw_settings if isinstance(raw_settings, dict) else data
        )
        method = str(data.get("method") or settings.get("correlation_method") or "pearson").strip()
        if method not in ("pearson", "spearman"):
            method = "pearson"
        raw_min_periods = data.get("min_periods")
        if raw_min_periods is None:
            raw_min_periods = settings.get("min_periods")
        try:
            min_periods = max(2, int(raw_min_periods or 30))
        except (TypeError, ValueError):
            min_periods = 30
        try:
            selection = selection_from_request(data, page_uuid=page_uuid)
        except AssertionError as exc:
            raise ValueError(str(exc) or "请先选择产品路径") from exc
        return cls(
            selection=selection,
            factor_family_alias=factor_family_alias,
            factor_alias=factor_alias,
            page_uuid=page_uuid,
            settings=settings,
            method=method,
            min_periods=min_periods,
        )

    @classmethod
    def from_run_spec(cls, data: dict[str, Any]) -> "FactorTypeAnalysisRun":
        owner = str(data.get("_owner") or data.get("owner_username") or "").strip()
        run_id = str(data.get("run_id") or data.get("run_token") or "").strip()
        if not owner or not run_id:
            raise ValueError("factor type analysis RunSpec requires owner and run_id")
        base = cls.from_request(data, page_uuid="")
        base.owner = owner
        base.run_id = run_id
        base.isolated = True
        base.external_factor_artifacts = list(
            data.get("external_factor_artifacts") or []
        )
        return base

    def run(self) -> dict[str, Any]:
        started_at = time.time()
        start_dt, end_dt = _run_window_datetimes(self.settings)

        # 1) 创建 FactorTester
        tester = (
            create_isolated_factor_tester_for_run(
                self.selection,
                run_id=self.run_id,
                start_dt=start_dt,
                end_dt=end_dt,
                user=user_obj_for_name(self.owner),
            )
            if self.isolated
            else create_factor_tester_for_run(
                self.selection,
                page_uuid=self.page_uuid,
                start_dt=start_dt,
                end_dt=end_dt,
                user=current_user_obj(),
            )
        )

        # 2) 计算目标因子
        target_factor = _load_and_calc_factor(
            tester,
            self.factor_family_alias,
            self.factor_alias,
            self.page_uuid,
            owner=self.owner,
            isolated=self.isolated,
            external_factor_artifacts=self.external_factor_artifacts,
        )
        require_factor_data_coverage(
            tester.products,
            target_factor,
            start_dt=start_dt,
            end_dt=end_dt,
            data_source=str((self.settings or {}).get("data_source") or ""),
        )

        # 3) 提取目标因子在各产品上的序列
        target_series = _product_series_from_tester(tester, target_factor)
        if not target_series:
            raise LookupError("目标因子没有可用的序列数据")

        # 4) 计算参照因子序列 — 需要先 calc 参照因子
        reference_series: dict[str, pd.Series] = {}
        skipped_refs = []
        asset_classes = _infer_asset_classes(self.selection)
        for ref_def in default_registry.list():
            skip_reason = _reference_skip_reason(ref_def, asset_classes)
            if skip_reason:
                skipped_refs.append({
                    "key": ref_def.key,
                    "name": ref_def.name,
                    "category": ref_def.category.value,
                    "category_label": ref_def.category.label_cn,
                    "reason": skip_reason,
                    "help_text": ref_def.help_text,
                })
                continue
            try:
                ref_factor = _load_and_calc_factor(
                    tester,
                    ref_def.factor_family_alias or self.factor_family_alias,
                    ref_def.factor_alias,
                    self.page_uuid,
                    allow_default_factor=getattr(ref_def, "reference_source", "") == "public_factor",
                    owner=self.owner,
                    isolated=self.isolated,
                )
                ref_series = _product_series_from_tester(tester, ref_factor)
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
                skipped_refs.append({
                    "key": ref_def.key,
                    "name": ref_def.name,
                    "category": ref_def.category.value,
                    "category_label": ref_def.category.label_cn,
                    "reason": "calculation_failed",
                    "help_text": ref_def.help_text,
                })
                continue

        # 5) 执行分析
        analyzer = FactorTypeAnalyzer(registry=default_registry)
        result = analyzer.analyze(
            target_series=target_series,
            factor_name=self.factor_alias,
            method=self.method,
            reference_series=reference_series,
            min_periods=self.min_periods,
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

        from server.services.external_factor_artifacts import result_metadata

        return {
            "success": True,
            "target_factor": {
                "alias": self.factor_alias,
                "family_alias": self.factor_family_alias,
            },
            "reference_factors": ref_details,
            "skipped_reference_factors": skipped_refs,
            "category_correlations": result.category_correlations,
            "best_match": result.best_match,
            "product_correlation": result.product_correlation,
            "product_type_profiles": result.product_type_profiles,
            "category_product_rankings": result.category_product_rankings,
            "product_summaries": product_summaries,
            "meta": {
                "elapsed_ms": round((time.time() - started_at) * 1000),
                "method": self.method,
                "min_periods": self.min_periods,
                "product_count": len(target_series),
                "reference_count": len(reference_series),
                "skipped_reference_count": len(skipped_refs),
                "asset_classes": list(asset_classes),
            },
            "external_factor_artifacts": result_metadata(
                self.external_factor_artifacts
            ),
        }

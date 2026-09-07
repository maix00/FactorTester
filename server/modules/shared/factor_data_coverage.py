"""Strict source selection and coverage checks for direct factor tests."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from tools.data.providers import DataProviderProductTS
from tools.data.types import DataFreq, DataTime
from tools.data.types.time_index import DataIndex


def _bound(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        # Coverage is expressed in the source market's wall-clock date.  UTC
        # conversion would turn Asia/Shanghai midnight into the previous day.
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


class FactorDataCoverageError(ValueError):
    """Stable, user-visible failure raised before factor execution."""

    def __init__(self, message: str, *, code: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def require_factor_data_coverage(
    products: Iterable[Any],
    factor: Any,
    *,
    start_dt: DataTime,
    end_dt: DataTime,
    data_source: str = "",
    warmup_window: pd.Timedelta | None = None,
    allow_all_warmup_fallback: bool = False,
) -> dict[str, Any]:
    """Check eligible sources while keeping output and warm-up ranges distinct."""
    from tools.factors.evaluation.source_frequency import resolve_source_frequency
    products = list(products)
    frequency = resolve_source_frequency(factor, products)
    source = None
    source_key = str(data_source or "").strip()
    # Typed IC configurations persist "auto"; it means the same per-product
    # source selection as an omitted source, not a provider registry key.
    if source_key and source_key != "auto":
        try:
            source = DataProviderProductTS[source_key]
        except Exception as exc:
            raise FactorDataCoverageError(
                f"数据源不存在: {source_key}",
                code="factor_data_source_invalid",
                details={"data_source": source_key},
            ) from exc
        if source.freq != frequency:
            raise FactorDataCoverageError(
                f"数据源 {source_key} 不提供因子计算频率 {frequency.name}",
                code="factor_data_source_frequency_mismatch",
                details={"data_source": source_key, "frequency": frequency.name},
            )

    requested_start = _bound(start_dt.ts)
    requested_end = _bound(end_dt.ts)
    warmup = pd.Timedelta(warmup_window or pd.Timedelta(0))
    required_start = _bound(pd.Timestamp(start_dt.ts) - warmup)
    failures: list[str] = []
    skipped: list[dict[str, str]] = []
    leading_gaps: list[dict[str, str]] = []
    warmup_fallbacks: list[dict[str, str]] = []
    eligible = 0
    for product in products:
        name = str(getattr(product, "name", product))
        try:
            view = getattr(product, frequency.name)
            if source is None and hasattr(view, "next_available_source"):
                if view.next_available_source() is None:
                    skipped.append({"product": name, "reason": "no_compatible_source"})
                    continue
            frame = view.get_data(copy=False, source=source)
            index = DataIndex(frame.index).signal_index
        except Exception as exc:
            skipped.append({"product": name, "reason": str(exc)})
            continue
        if len(index) == 0:
            skipped.append({"product": name, "reason": "empty_source"})
            continue
        eligible += 1
        available_start = _bound(index.min())
        available_end = _bound(index.max())
        if available_start > requested_end:
            eligible -= 1
            skipped.append({
                "product": name,
                "reason": "no_data_in_formal_window",
            })
            continue
        if available_end < requested_end:
            failures.append(
                f"{name}: 可用范围 {available_start.date()} 至 {available_end.date()}"
            )
            continue
        if warmup > pd.Timedelta(0) and available_start > required_start:
            eligible -= 1
            shortfall = {
                "product": name,
                "reason": "insufficient_warmup",
                "required_data_start": str(required_start.date()),
                "available_start": str(available_start.date()),
            }
            skipped.append(shortfall)
            warmup_fallbacks.append(shortfall)
        elif available_start > requested_start:
            # With no warm-up, the expression is allowed to produce NaN until
            # enough in-window observations have accumulated.
            leading_gaps.append({
                "product": name,
                "available_start": str(available_start.date()),
            })
    if eligible == 0 and allow_all_warmup_fallback and warmup_fallbacks:
        # Automatic warm-up is best effort when its strict interpretation
        # would discard every otherwise usable product. Keep the formal run
        # executable and expose the leading NaN trade-off in the result.
        skipped = [item for item in skipped if item not in warmup_fallbacks]
        eligible = len(warmup_fallbacks)
    else:
        warmup_fallbacks = []
    details = {
        "formal_start": str(requested_start.date()),
        "formal_end": str(requested_end.date()),
        "required_data_start": str(required_start.date()),
        "warmup_window": str(warmup) if warmup > pd.Timedelta(0) else None,
        "eligible_product_count": eligible,
        "skipped_products": skipped,
        "leading_gaps": leading_gaps,
        "warmup_fallbacks": warmup_fallbacks,
    }
    if eligible == 0:
        raise FactorDataCoverageError(
            f"没有产品可提供因子计算频率 {frequency.name} 的数据",
            code="factor_data_source_unavailable",
            details=details,
        )
    if failures:
        detail = "；".join(failures[:12])
        raise FactorDataCoverageError(
            "数据源未覆盖测试时间范围 "
            f"{required_start.date()} 至 {requested_end.date()}：{detail}",
            code="factor_data_coverage_unavailable",
            details={**details, "failures": failures},
        )
    return details


__all__ = ["FactorDataCoverageError", "require_factor_data_coverage"]


def apply_factor_data_coverage(tester: Any, coverage: dict[str, Any]) -> list[dict[str, Any]]:
    """Remove ineligible products only from this run; retain an auditable summary."""
    skipped = coverage.get("skipped_products", [])
    excluded = {item["product"] for item in skipped}
    tester.products = type(tester.products)(p for p in tester.products if str(getattr(p, "name", p)) not in excluded)
    reasons = {
        "insufficient_warmup": "预热数据不足",
        "no_data_in_formal_window": "测试时间范围内无数据",
        "no_compatible_source": "无兼容数据源",
        "empty_source": "数据源为空",
    }
    rows = [{
        "type": "产品路径", "status": "已移除", "level": "warning",
        "code": "factor_data_product_removed",
        "detail": item["product"] + "：" + reasons.get(item["reason"], item["reason"])
        + (f"（预热需要从 {item['required_data_start']} 开始，可用数据从 {item['available_start']} 开始）"
           if item["reason"] == "insufficient_warmup" else ""),
        "details": item,
    } for item in skipped]
    rows.extend({
        "type": "产品路径", "status": "自动预热降级", "level": "warning",
        "code": "factor_data_warmup_fallback",
        "detail": (
            item["product"] + "：没有足够的自动预热数据，已从正式开始日计算；"
            "起始段可能产生 NaN"
        ),
        "details": item,
    } for item in coverage.get("warmup_fallbacks", []))
    return rows

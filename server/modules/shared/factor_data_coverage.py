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
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.normalize()


def _source_frequency(factor: Any) -> DataFreq:
    family = getattr(factor, "family", None)
    value = getattr(family, "source_freq", None) or getattr(factor, "freq", None)
    if value is None:
        raise ValueError("因子没有声明计算数据频率")
    return DataFreq(value)


def require_factor_data_coverage(
    products: Iterable[Any],
    factor: Any,
    *,
    start_dt: DataTime,
    end_dt: DataTime,
    data_source: str = "",
) -> None:
    """Reject missing sources and source ranges before factor evaluation."""
    frequency = _source_frequency(factor)
    source = None
    source_key = str(data_source or "").strip()
    if source_key:
        try:
            source = DataProviderProductTS[source_key]
        except Exception as exc:
            raise ValueError(f"数据源不存在: {source_key}") from exc
        if source.freq != frequency:
            raise ValueError(
                f"数据源 {source_key} 不提供因子计算频率 {frequency.name}"
            )

    requested_start = _bound(start_dt.ts)
    requested_end = _bound(end_dt.ts)
    failures: list[str] = []
    for product in products:
        name = str(getattr(product, "name", product))
        try:
            view = getattr(product, frequency.name)
            frame = view.get_data(copy=False, source=source)
            index = DataIndex(frame.index).signal_index
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        if len(index) == 0:
            failures.append(f"{name}: 数据为空")
            continue
        available_start = _bound(index.min())
        available_end = _bound(index.max())
        if available_start > requested_start or available_end < requested_end:
            failures.append(
                f"{name}: 可用范围 {available_start.date()} 至 {available_end.date()}"
            )
    if failures:
        detail = "；".join(failures[:12])
        raise ValueError(
            "数据源未覆盖测试时间范围 "
            f"{requested_start.date()} 至 {requested_end.date()}：{detail}"
        )


__all__ = ["require_factor_data_coverage"]

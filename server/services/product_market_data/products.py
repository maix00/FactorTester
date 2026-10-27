"""Product-level price-series projection for Manager and service routes."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from server.modules.shared.price_data_helpers import (
    format_price_row,
    open_interest_column,
)
from server.modules.shared.price_services import (
    available_freq_names_for_product,
    available_sources_for_product,
    cached_products,
    contract_has_data,
    find_product,
    product_public_fields,
    supports_adjusted_price,
    supports_term_structure,
)
from tools.data.providers import DataProviderProductTS as DataSource
from tools.data.types import DataFreq, finest_index
from tools.products.Futures import Futures
from tools.products.product_utils import get_product_contracts

from .errors import ProductMarketDataError
from .ranges import latest_relative_start, range_bound
from .shared_read import chart_request, parquet_frame
from .sampling import bounded_ohlcv_frame, bounded_ohlcv_rows, fixed_chart_frame


def _frequency(payload: Mapping[str, Any]):
    source_alias = str(payload.get("data_source") or "")
    if source_alias:
        try:
            source = DataSource[source_alias]
        except Exception as exc:
            raise ProductMarketDataError(
                f"数据源不存在: {source_alias}",
            ) from exc
        return source.freq, source
    try:
        return DataFreq(str(payload.get("freq") or "DAY1")), None
    except Exception:
        return DataFreq("DAY1"), None


def _series_product(product, product_name: str, payload: Mapping[str, Any]):
    requested_adjusted = bool(payload.get("adjusted", False))
    variant = str(
        payload.get("series_variant")
        or ("primary_adjusted" if requested_adjusted else "primary_raw")
    )
    refs = {
        ref.variant: ref
        for ref in getattr(product, "get_series_variants", lambda: [])()
    }
    series_ref = refs.get(variant)
    if series_ref is None:
        raise ProductMarketDataError(f"品种不支持序列: {variant}")
    if series_ref.backing_product_name != product_name:
        backing = type(product)(series_ref.backing_product_name)
        product = backing
    adjusted = bool(series_ref.adjusted and supports_adjusted_price(product))
    return product, variant, adjusted


def _select_product_data(product, payload: Mapping[str, Any]):
    frequency, requested_source = _frequency(payload)
    candidates = DataSource.available_for_product(product)
    if requested_source is not None:
        if requested_source not in candidates:
            raise ProductMarketDataError(f"数据源不可用于该品种: {requested_source.key}")
        return requested_source.freq, requested_source
    selected = next((source for source in candidates if source.freq == frequency), None)
    if selected is None:
        selected = next(iter(candidates), None)
    if selected is None:
        raise ProductMarketDataError("无可用数据源")
    return selected.freq, selected


def _source_chart_frame(product, source, frequency, payload, start, end):
    import pyarrow.parquet as pq
    path = source.get_path(product)
    reader = pq.ParquetFile(path)
    schema = reader.schema_arrow
    available = set(schema.names)
    times = {str(raw): str(canonical) for raw, canonical in source.time_cols_mapping.items()}
    values = {str(raw): str(canonical) for raw, canonical in source.data_cols_mapping.items()}
    raw_time = next((raw for raw, canonical in times.items() if canonical == frequency.name), None)
    if raw_time is None:
        raise ProductMarketDataError("数据源缺少对应频率的时间字段")
    columns = [raw for raw in available if raw in times or values.get(raw) in {
        "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME", "OPEN_INTEREST",
        "OPEN_ADJUSTED", "HIGH_ADJUSTED", "LOW_ADJUSTED", "CLOSE_ADJUSTED",
        "ADJUSTMENT_MUL", "ADJUSTMENT_ADD"}]
    chart_range = str(payload.get("chart_range") or "").lower()
    if chart_range:
        column_index = schema.get_field_index(raw_time)
        latest = [reader.metadata.row_group(i).column(column_index).statistics
                  for i in range(reader.metadata.num_row_groups)]
        if not all(stats is not None and stats.has_min_max for stats in latest):
            raise ProductMarketDataError("数据源缺少覆盖范围元数据，请指定时间范围")
        if latest:
            relative = latest_relative_start(pd.DatetimeIndex([max(stats.max for stats in latest)]), chart_range)
            if relative is not None:
                start = max(start, relative.tz_localize(None) if relative.tzinfo else relative)
    zone = getattr(product, "timezone", None) or "Asia/Shanghai"
    dtype = schema.field(raw_time).type
    def bound(value):
        if getattr(dtype, "tz", None):
            return (value.tz_localize(zone) if value.tzinfo is None else value).tz_convert(dtype.tz)
        return value.tz_convert(zone).tz_localize(None) if value.tzinfo else value
    filters = [(raw_time, ">=", bound(start)), (raw_time, "<=", bound(end))]
    adjusted = bool(payload.get("adjusted", False))
    requested = ("OPEN_ADJUSTED", "HIGH_ADJUSTED", "LOW_ADJUSTED", "CLOSE_ADJUSTED", "VOLUME") if adjusted else ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME")
    fixed = payload.get("chart_mode") == "fixed"
    def fold(frame):
        try:
            return fixed_chart_frame(frame, payload, requested, frequency,
                open_interest_column(frame.columns),
                trading_day_column="__trading_day__" if "__trading_day__" in frame else None,
                source_delivery_mode=getattr(source, "delivery_mode", "historical_snapshot"))[0]
        except ProductMarketDataError as exc:
            raise ProductMarketDataError("当前范围超过图表资源上限，请选择更粗频率或更短范围") from exc
    previous_time = None
    def shape(frame):
        nonlocal previous_time
        frame = frame.rename(columns={**values, **times})
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame[frequency.name]))
        if not frame.index.is_monotonic_increasing or frame.index.has_duplicates or (
            previous_time is not None and len(frame) and frame.index[0] <= previous_time
        ):
            raise ProductMarketDataError("数据源行情未按时间唯一排序")
        if len(frame): previous_time = frame.index[-1]
        if "DAY1" in frame and frequency.name != "DAY1":
            frame["__trading_day__"] = pd.to_datetime(frame["DAY1"])
        if adjusted:
            for column in ("OPEN", "HIGH", "LOW", "CLOSE"):
                if column+"_ADJUSTED" not in frame:
                    if "ADJUSTMENT_MUL" not in frame or "ADJUSTMENT_ADD" not in frame:
                        raise ProductMarketDataError("数据源没有请求的复权序列")
                    frame[column+"_ADJUSTED"] = frame[column]*frame["ADJUSTMENT_MUL"]+frame["ADJUSTMENT_ADD"]
        return fold(frame) if fixed else frame
    frame = parquet_frame(path, columns=columns, filters=filters, transform=shape,
                          combine=fold if fixed else None)
    return frame


def _price_rows(product, frame: pd.DataFrame, adjusted: bool, frequency, *, daily_labels=False):
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(finest_index(frame.index))
    timezone = getattr(product, "timezone", None) or "Asia/Shanghai"
    if frame.index.tz is not None and str(frame.index.tz) != timezone:
        frame.index = frame.index.tz_convert(timezone)
    columns = (
        ("OPEN_ADJUSTED", "HIGH_ADJUSTED", "LOW_ADJUSTED", "CLOSE_ADJUSTED", "VOLUME")
        if adjusted else ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME")
    )
    oi_column = open_interest_column(frame.columns)
    emitted = frame.assign(__time__=frame.index)
    rows = [
        format_price_row(
            row=row,
            time_col="__time__",
            o_col=columns[0],
            h_col=columns[1],
            l_col=columns[2],
            c_col=columns[3],
            v_col=columns[4],
            oi_col=oi_column,
            freq_is_daily=frequency.is_day_multiple() or daily_labels,
            timezone=timezone,
            trading_day_close_time=getattr(product, "trading_day_close_time", None),
        )
        for _, row in emitted.iterrows()
    ]
    return rows, oi_column is not None


def _adjustment_metadata(product, adjusted: bool) -> dict[str, str]:
    """Describe the meaning of the selected price series.

    Futures ``adjusted`` columns are the continuous-contract roll series
    generated by ``ProductDataView``.  They are not stock dividend/rights
    adjustments, so the API must expose that distinction to clients.
    """
    if not adjusted:
        return {"method": "raw", "formula": ""}
    if isinstance(product, Futures):
        return {
            "method": "continuous_futures_roll",
            "formula": "raw × adjustment_mul + adjustment_add",
        }
    return {
        "method": "adjusted_source",
        "formula": "source-provided adjusted OHLC",
    }


def _contract_ranges(product, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not supports_term_structure(product):
        return []
    try:
        raw = get_product_contracts(
            product,
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
        )
    except Exception:
        return []
    return [{
        "contract": item["contract"],
        "uid": item["uid"],
        "has_data": contract_has_data(item["uid"]),
        "start_ts": item.get("start_ts"),
        "end_ts": item.get("end_ts"),
    } for item in raw]


@chart_request
def product_price_series(payload: Mapping[str, Any]) -> dict[str, Any]:
    product_name = str(payload.get("product_name") or "")
    if not product_name:
        raise ProductMarketDataError("缺少 product_name")
    product = find_product(cached_products(), product_name)
    if product is None:
        raise ProductMarketDataError(f"未找到品种: {product_name}", 404)
    product, variant, adjusted = _series_product(product, product_name, payload)
    start = range_bound(
        payload.get("start_date"), payload.get("start_time"),
        is_end=False, precision=payload.get("time_precision"),
    )
    end = range_bound(
        payload.get("end_date"), payload.get("end_time"),
        is_end=True, precision=payload.get("time_precision"),
    )
    if start is None:
        start = pd.Timestamp("2000-01-01")
    if end is None:
        end = pd.Timestamp.now()

    frequency, source = _select_product_data(product, payload)
    frame = _source_chart_frame(product, source, frequency,
                                {**payload, "adjusted": adjusted}, start, end)
    if frame is None or frame.empty:
        raise ProductMarketDataError("指定范围内无价格数据", 404)
    price_columns = (
        ("OPEN_ADJUSTED", "HIGH_ADJUSTED", "LOW_ADJUSTED", "CLOSE_ADJUSTED", "VOLUME")
        if adjusted else ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME")
    )
    fixed_chart = payload.get("chart_mode") == "fixed"
    if fixed_chart:
        total_count = len(frame)
    else:
        frame, total_count = bounded_ohlcv_frame(
            frame, payload, price_columns, open_interest_column(frame.columns),
        )
    rows, has_open_interest = _price_rows(product, frame, adjusted, frequency,
        daily_labels=str(payload.get("chart_interval") or "").upper() == "DAY1")
    if not fixed_chart:
        rows, _ = bounded_ohlcv_rows(rows, payload)
    adjustment = _adjustment_metadata(product, adjusted)
    term_structure = supports_term_structure(product)
    return {
        "success": True,
        "product": product_name,
        "desc": getattr(product, "desc", product_name),
        "product_type": "futures" if isinstance(product, Futures) else "product",
        "is_term_contract": False,
        "adjusted": adjusted,
        "series_variant": variant,
        "adjustment_method": adjustment["method"],
        "adjustment_formula": adjustment["formula"],
        "supports_adjusted": supports_adjusted_price(product),
        "supports_term_structure": term_structure,
        "freq": frequency.name,
        "timezone": str(getattr(product, "timezone", None) or "Asia/Shanghai"),
        "data_source": (
            getattr(source, "alias", "")
            or getattr(source, "key", "")
        ),
        "delivery_mode": getattr(source, "delivery_mode", "historical_snapshot"),
        "available_sources": available_sources_for_product(product),
        "available_freqs": available_freq_names_for_product(product),
        "count": total_count,
        "returned_count": len(rows),
        "has_oi": has_open_interest,
        "contracts": _contract_ranges(product, payload),
        "fields": product_public_fields(product),
        "data": rows,
    }

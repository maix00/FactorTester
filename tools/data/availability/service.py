"""Provider-neutral construction of compact data availability profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.data.types import DataFreq

from .model import profile_document
from .parquet_footer import inspect_parquet
from .schema import availability_dimensions


def build_availability_profile(
    *,
    products: Iterable[Any],
    sources: Iterable[Any],
    as_of: datetime | None = None,
    required_fields: Iterable[str] | None = None,
    include_field_catalog: bool = False,
) -> dict[str, Any]:
    product_list = list(products)
    source_list = list(sources)
    field_list = list(required_fields or [])
    entries = [
        _inspect_source(
            product,
            source,
            required_fields=field_list,
            include_field_catalog=include_field_catalog,
        )
        for product in product_list
        for source in source_list
    ]
    return profile_document(
        product_scope=[_product_name(product) for product in product_list],
        entries=entries,
        as_of=as_of or datetime.now(timezone.utc),
    )


def _inspect_source(
    product: Any,
    source: Any,
    *,
    required_fields: list[str],
    include_field_catalog: bool,
) -> dict[str, Any]:
    product_name = _product_name(product)
    source_key = str(getattr(source, "key", source))
    frequency = _frequency_name(getattr(source, "freq", None))
    base = {
        "product": product_name,
        "source": source_key,
        **availability_dimensions(
            sampling_mode="bar",
            frequency=frequency,
            data_kind="ohlcv_bar",
            market_depth="not_applicable",
            delivery_mode="historical_snapshot",
        ),
    }
    if not _timezone_matches(product, source):
        return {
            **base,
            "status": "unavailable",
            "reason": "timezone_mismatch",
        }
    try:
        path = Path(source.get_path(product))
    except Exception:
        return {
            **base,
            "status": "unavailable",
            "reason": "path_resolution_failed",
        }
    if path.suffix.lower() != ".parquet":
        return {
            **base,
            "status": "unavailable",
            "reason": "coverage_inspector_not_registered",
        }
    details = inspect_parquet(
        path,
        time_columns=tuple(getattr(source, "time_cols_mapping", {}).keys()),
        data_columns=dict(getattr(source, "data_cols_mapping", {})),
        required_fields=tuple(required_fields),
        include_field_catalog=include_field_catalog,
        time_columns_mapping=dict(getattr(source, "time_cols_mapping", {})),
    )
    if details.get("status") != "available":
        return {**base, **details}
    result = {
        **base,
        "status": "available",
        "frequency": frequency,
        "coverage": details["coverage"],
        "updated_at": details["updated_at"],
    }
    if "required_fields" in details:
        result["required_fields"] = details["required_fields"]
    if "field_catalog" in details:
        result["field_catalog"] = details["field_catalog"]
        result["time_fields"] = details["time_fields"]
    return result


def _product_name(product: Any) -> str:
    return str(getattr(product, "name", getattr(product, "alias", product)))


def _frequency_name(value: Any) -> str:
    try:
        return DataFreq(value).name
    except Exception:
        return str(value)


def _timezone_matches(product: Any, source: Any) -> bool:
    product_timezone = getattr(product, "timezone", None)
    source_timezone = getattr(source, "timezone", None)
    return product_timezone == source_timezone

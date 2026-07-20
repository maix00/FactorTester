"""Provider-neutral construction of compact data availability profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.data.types import DataFreq

from .model import profile_document
from .parquet_footer import inspect_parquet


def build_availability_profile(
    *,
    products: Iterable[Any],
    sources: Iterable[Any],
    as_of: datetime | None = None,
) -> dict[str, Any]:
    product_list = list(products)
    source_list = list(sources)
    entries = [
        _inspect_source(product, source)
        for product in product_list
        for source in source_list
    ]
    return profile_document(
        product_scope=[_product_name(product) for product in product_list],
        entries=entries,
        as_of=as_of or datetime.now(timezone.utc),
    )


def _inspect_source(product: Any, source: Any) -> dict[str, Any]:
    product_name = _product_name(product)
    source_key = str(getattr(source, "key", source))
    frequency = _frequency_name(getattr(source, "freq", None))
    base = {
        "product": product_name,
        "source": source_key,
        "mode": "historical_snapshot",
    }
    if not _timezone_matches(product, source):
        return {
            **base,
            "status": "unavailable",
            "frequency": frequency,
            "reason": "timezone_mismatch",
        }
    try:
        path = Path(source.get_path(product))
    except Exception:
        return {
            **base,
            "status": "unavailable",
            "frequency": frequency,
            "reason": "path_resolution_failed",
        }
    if path.suffix.lower() != ".parquet":
        return {
            **base,
            "status": "unavailable",
            "frequency": frequency,
            "reason": "coverage_inspector_not_registered",
        }
    details = inspect_parquet(
        path,
        time_columns=tuple(getattr(source, "time_cols_mapping", {}).keys()),
        source_key=source_key,
        product_name=product_name,
        frequency=frequency,
    )
    if details.get("status") != "available":
        return {**base, "frequency": frequency, **details}
    return {
        **base,
        "status": "available",
        "frequency": frequency,
        "coverage": details["coverage"],
        "updated_at": details["updated_at"],
        "replayable": True,
        "point_in_time": False,
        "snapshot_ref": details["snapshot_ref"],
    }


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

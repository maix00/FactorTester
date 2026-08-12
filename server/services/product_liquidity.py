"""Batch point-in-time product-liquidity evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.modules.shared.price_services import cached_products
from tools.data.availability.model import canonical_hash
from tools.data.product_liquidity import summarize_day1_volume_batch
from tools.data.providers.DataProviderProductTS import DataProviderProductTS
from tools.data.providers.DistributedComponents import LocalPathResolver
from tools.data.types import DataColumn, DataFreq


def product_liquidity_for_scope(
    *,
    product_names: list[str],
    source_name: str,
    as_of: str,
    window_days: int,
) -> dict[str, Any]:
    """Return hash-bound DAY1 volume evidence for one explicit product batch."""
    names = _unique_nonempty(product_names, field="product_names")
    source_key = str(source_name).strip()
    if not source_key:
        raise ValueError("source_name must not be empty")
    products = _resolve_products(names)
    source = _resolve_source(source_key)
    if source.freq != DataFreq.DAY1:
        raise ValueError(f"数据源 {source_key} 不是 DAY1 数据源")
    if not isinstance(getattr(source, "_path_resolver", None), LocalPathResolver):
        raise ValueError(
            f"数据源 {source_key} 不是可批量扫描的本地文件数据源；"
            "请登记相应 liquidity connector"
        )
    day_column = _physical_column(source.time_cols_mapping, DataFreq.DAY1.name)
    volume_column = _physical_column(source.data_cols_mapping, DataColumn.VOLUME.name)
    paths: dict[str, str | None] = {}
    for product in products:
        try:
            paths[product.name] = source.get_path(product)
        except Exception:
            paths[product.name] = None
    source_snapshot_hash = _snapshot_hash(paths)
    entries = summarize_day1_volume_batch(
        product_paths=paths,
        day_column=day_column,
        volume_column=volume_column,
        as_of=as_of,
        window_days=window_days,
    )
    body = {
        "schema_version": 1,
        "evidence_kind": "product_liquidity",
        "product_scope": names,
        "source": source_key,
        "frequency": DataFreq.DAY1.name,
        "as_of": str(as_of),
        "window_days": int(window_days),
        "source_snapshot_hash": source_snapshot_hash,
        "metric_definition": {
            "daily_volume": "sum_of_non_null_volume_rows_per_trading_day",
            "average_daily_volume": "mean_over_observed_days_in_requested_window",
            "zero_volume_days": "observed_days_with_daily_volume_less_than_or_equal_to_zero",
            "missing_calendar_days": "not_counted_as_zero",
            "window_anchor": "explicit_as_of_inclusive",
        },
        "read_strategy": {
            "mode": "single_pyarrow_dataset_scan",
            "requested_product_count": len(paths),
            "candidate_file_count": sum(
                isinstance(path, str) and Path(path).expanduser().is_file()
                for path in paths.values()
            ),
            "projected_columns": [day_column, volume_column],
            "database_reads": 0,
        },
        "entries": entries,
    }
    return {**body, "evidence_hash": canonical_hash(body)}


def _resolve_products(names: list[str]) -> list[Any]:
    registered = {
        str(getattr(product, "name", getattr(product, "alias", product))): product
        for product in cached_products()
        if product is not None
    }
    missing = [name for name in names if name not in registered]
    if missing:
        raise LookupError(f"未找到产品: {', '.join(missing)}")
    return [registered[name] for name in names]


def _resolve_source(name: str) -> DataProviderProductTS:
    from sources.registry import load_all_sources

    load_all_sources()
    source = next(
        (item for item in DataProviderProductTS.all() if str(item.key) == name),
        None,
    )
    if source is None:
        raise LookupError(f"未找到数据源: {name}")
    return source


def _physical_column(mapping: dict[Any, Any], logical_name: str) -> str:
    matches = [str(raw) for raw, logical in mapping.items() if str(logical) == logical_name]
    if len(matches) != 1:
        raise ValueError(f"数据源未提供唯一的 {logical_name} 物理字段映射")
    return matches[0]


def _snapshot_hash(paths: dict[str, str | None]) -> str:
    items = []
    for product, raw_path in sorted(paths.items()):
        if not isinstance(raw_path, str) or not raw_path.strip():
            items.append({"product": product, "unresolved": True})
            continue
        path = Path(raw_path).expanduser().resolve()
        if path.is_file():
            stat = path.stat()
            items.append({
                "product": product,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            })
        else:
            items.append({"product": product, "missing": True})
    return canonical_hash(items)


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    normalized = [str(item).strip() for item in values if str(item).strip()]
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must contain unique values")
    return normalized

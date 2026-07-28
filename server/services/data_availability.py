"""Resolve explicit product/data-source scope into an availability profile."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from server.modules.shared.price_services import cached_products
from tools.data.availability import build_availability_profile
from tools.data.availability.model import profile_document
from tools.data.availability.registry import availability_connector
from tools.data.field_history import summarize_historical_field_coverage
from tools.data.providers import DataProviderProductTS
from tools.data.providers.DataProviderProductTSBundle import (
    DataProviderProductTSBundle,
)
from tools.data.types import DataFreq


def availability_for_scope(
    *,
    product_names: list[str],
    source_names: list[str],
    frequency_names: list[str] | None = None,
    probe: bool = False,
    expanded: bool = False,
    required_fields: list[str] | None = None,
    include_field_catalog: bool = False,
    include_historical_fields: bool = False,
    inspection_runtime: str = "server",
) -> dict[str, Any]:
    """Inspect exactly the requested scope without widening it through fallback."""
    _ensure_sources_registered()
    products = _resolve_products(product_names)
    frequencies = _normalise_frequencies(frequency_names or [])
    sources, connectors = _resolve_sources(source_names, frequencies)
    from datetime import datetime, timezone

    as_of = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    if sources:
        entries.extend(build_availability_profile(
            products=products,
            sources=sources,
            as_of=as_of,
            required_fields=required_fields,
            include_field_catalog=include_field_catalog,
        )["entries"])
    for connector in connectors:
        entries.extend(connector.inspect(
            products,
            probe=probe,
            expanded=expanded,
        ))
    history = (
        summarize_historical_field_coverage(product_names)
        if include_historical_fields
        else None
    )
    return profile_document(
        product_scope=list(product_names),
        source_scope=list(source_names),
        frequency_scope=frequencies,
        probe=probe,
        expanded=expanded,
        required_fields=list(required_fields or []),
        include_field_catalog=include_field_catalog,
        include_historical_fields=include_historical_fields,
        historical_fields=history,
        inspection_runtime=inspection_runtime,
        entries=entries,
        as_of=as_of,
    )


@lru_cache(maxsize=1)
def _ensure_sources_registered() -> None:
    from sources.registry import load_all_sources

    load_all_sources()


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


def _resolve_sources(
    names: list[str],
    frequencies: list[str],
) -> tuple[list[Any], list[Any]]:
    registered = {
        str(getattr(source, "key", source)): source
        for source in DataProviderProductTS.all()
    }
    resolved: list[Any] = []
    connectors: list[Any] = []
    missing: list[str] = []
    for name in names:
        provider = registered.get(name)
        connector = availability_connector(name)
        if isinstance(provider, DataProviderProductTSBundle):
            resolved.extend(_filter_by_frequency(provider.members, frequencies))
        elif provider is not None:
            resolved.extend(_filter_by_frequency((provider,), frequencies))
        if connector is not None:
            connectors.append(connector)
        if provider is None and connector is None:
            missing.append(name)
    if missing:
        raise LookupError(f"未找到数据源: {', '.join(missing)}")
    unique = {str(getattr(source, "key", source)): source for source in resolved}
    return list(unique.values()), connectors


def _normalise_frequencies(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        try:
            normalized = DataFreq(value).name
        except (TypeError, ValueError) as exc:
            raise ValueError(f"无效数据频率: {value}") from exc
        if normalized not in result:
            result.append(normalized)
    return result


def _filter_by_frequency(
    sources: tuple[Any, ...],
    frequencies: list[str],
) -> tuple[Any, ...]:
    if not frequencies:
        return sources
    requested = set(frequencies)
    return tuple(
        source for source in sources
        if DataFreq(getattr(source, "freq", None)).name in requested
    )

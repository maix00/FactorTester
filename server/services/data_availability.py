"""Resolve explicit product/data-source scope into an availability profile."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from server.modules.shared.price_services import cached_products
from tools.data.availability import build_availability_profile
from tools.data.availability.model import profile_document
from tools.data.availability.registry import availability_connector
from tools.data.providers import DataProviderProductTS
from tools.data.providers.DataProviderProductTSBundle import (
    DataProviderProductTSBundle,
)


def availability_for_scope(
    *,
    product_names: list[str],
    source_names: list[str],
    probe: bool = False,
    expanded: bool = False,
) -> dict[str, Any]:
    """Inspect exactly the requested scope without widening it through fallback."""
    _ensure_sources_registered()
    products = _resolve_products(product_names)
    sources, connectors = _resolve_sources(source_names)
    from datetime import datetime, timezone

    as_of = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    if sources:
        entries.extend(build_availability_profile(
            products=products,
            sources=sources,
            as_of=as_of,
        )["entries"])
    for connector in connectors:
        entries.extend(connector.inspect(
            products,
            probe=probe,
            expanded=expanded,
        ))
    return profile_document(
        product_scope=list(product_names),
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


def _resolve_sources(names: list[str]) -> tuple[list[Any], list[Any]]:
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
            resolved.extend(provider.members)
        elif provider is not None:
            resolved.append(provider)
        if connector is not None:
            connectors.append(connector)
        if provider is None and connector is None:
            missing.append(name)
    if missing:
        raise LookupError(f"未找到数据源: {', '.join(missing)}")
    unique = {str(getattr(source, "key", source)): source for source in resolved}
    return list(unique.values()), connectors

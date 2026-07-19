"""Resolve explicit product/data-source scope into an availability profile."""

from __future__ import annotations

from typing import Any

from server.modules.shared.price_services import cached_products
from sources.Local.data_source_bundle import data_sources_for_bundle
from tools.data.availability import build_availability_profile
from tools.data.providers import DataProviderProductTS


def availability_for_scope(
    *,
    product_names: list[str],
    source_names: list[str],
    probe: bool = False,
    expanded: bool = False,
) -> dict[str, Any]:
    """Inspect exactly the requested scope without widening it through fallback."""
    del probe, expanded
    products = _resolve_products(product_names)
    sources = _resolve_sources(source_names)
    return build_availability_profile(products=products, sources=sources)


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


def _resolve_sources(names: list[str]) -> list[Any]:
    registered = {
        str(getattr(source, "key", source)): source
        for source in DataProviderProductTS.all()
    }
    resolved: list[Any] = []
    missing: list[str] = []
    for name in names:
        bundle_members = data_sources_for_bundle(name)
        if bundle_members:
            resolved.extend(bundle_members)
        elif name in registered:
            resolved.append(registered[name])
        else:
            missing.append(name)
    if missing:
        raise LookupError(f"未找到数据源: {', '.join(missing)}")
    unique = {str(getattr(source, "key", source)): source for source in resolved}
    return list(unique.values())

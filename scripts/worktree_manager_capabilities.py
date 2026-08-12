"""Server-local market-data capability snapshots for federated Managers.

The source catalog is the authority for product/source/frequency semantics.
This module only turns those declarations into a JSON-safe, bounded projection
that a Manager can expose to peers and the Web UI.  It deliberately reports
actual available data, not only a source's declared product scope.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from tools.data.types import DataFreq


CAPABILITY_SCHEMA_VERSION = 1


def _text(value: object) -> str:
    return str(value or "").strip()


def _product_name(product: Any) -> str:
    return _text(
        getattr(product, "name", "")
        or getattr(product, "alias", "")
        or getattr(product, "code", "")
        or product
    )


def _product_ref(product: Any) -> str:
    from tools.products.classifier_paths import classifier_object_path

    try:
        return f"product:{classifier_object_path(product)}"
    except Exception:
        return f"product:{_product_name(product)}"


def _frequency_name(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        return DataFreq(value).name
    except Exception:
        return _text(value).upper()


def _frequency_compatible(available: str, requested: str) -> bool:
    if not requested:
        return True
    try:
        available_value = DataFreq(available).value
        requested_value = DataFreq(requested).value
        return (
            available_value > 0
            and requested_value > 0
            and requested_value.total_seconds()
            % available_value.total_seconds() == 0
        )
    except Exception:
        return available == requested


def _normalise_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = value.replace("，", ",").split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        values = [value]
    return list(dict.fromkeys(
        _text(item) for item in values if _text(item)
    ))


def _load_catalog() -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    from sources.registry import load_all_sources
    from server.modules.shared.price_services import cached_products
    from tools.data.source_catalog import data_source_declarations

    load_all_sources()
    return tuple(data_source_declarations()), tuple(cached_products())


def _member_summary(member: Any, products: tuple[Any, ...]) -> dict[str, object]:
    supported = [
        _product_name(product)
        for product in products
        if member.supports_product(product)
    ]
    available = [
        _product_name(product)
        for product in products
        if member.has_available_data(product)
    ]
    return {
        "id": _text(getattr(member, "key", "")),
        "label": _text(getattr(member, "label", "")),
        "frequency": _frequency_name(getattr(member, "frequency", "")),
        "timezone": _text(getattr(member, "timezone", "")),
        "dimensions": dict(getattr(member, "dimensions", {}) or {}),
        "catalog_product_count": len(supported),
        "available_product_count": len(available),
    }

def _source_summary(
    declaration: Any,
    products: tuple[Any, ...],
    *,
    include_products: bool,
) -> dict[str, object]:
    members = tuple(declaration.members)
    member_rows = [_member_summary(member, products) for member in members]
    supported = {
        _product_name(product)
        for product in products
        if declaration.supports_product(product)
    }
    available = {
        _product_name(product)
        for product in products
        if declaration.has_available_data(product)
    }
    frequencies = sorted({
        _frequency_name(getattr(member, "frequency", ""))
        for member in members
        if _frequency_name(getattr(member, "frequency", ""))
    })
    row: dict[str, object] = {
        "id": _text(getattr(declaration, "key", "")),
        "source_name": _text(getattr(declaration, "label", "")),
        "provider_kind": _text(getattr(declaration, "provider_kind", "")),
        "server_provided": True,
        "members": member_rows,
        "frequencies": frequencies,
        "catalog_product_count": len(supported),
        "available_product_count": len(available),
        "availability": {
            "status": "ready" if available else getattr(
                declaration, "empty_status", "empty",
            ),
            "product_count": len(available),
            "frequency_names": frequencies,
        },
    }
    if include_products:
        row["products"] = sorted(supported)
        row["available_products"] = sorted(available)
    return row


def _resolve_products(
    products: tuple[Any, ...], requested: Iterable[str],
) -> tuple[list[str], list[Any]]:
    by_name: dict[str, Any] = {}
    for product in products:
        name = _product_name(product)
        if name:
            by_name[name] = product
            for key in (
                getattr(product, "alias", ""),
                getattr(product, "code", ""),
            ):
                if _text(key):
                    by_name.setdefault(_text(key), product)
    names: list[str] = []
    resolved: list[Any] = []
    for value in requested:
        product = by_name.get(value)
        if product is None:
            names.append(value)
            continue
        name = _product_name(product)
        if name not in names:
            names.append(name)
            resolved.append(product)
    return names, resolved


def _source_matches(declaration: Any, member: Any, requested: str) -> bool:
    if not requested:
        return True
    wanted = requested.casefold()
    values = {
        _text(getattr(declaration, "key", "")),
        _text(getattr(declaration, "label", "")),
        _text(getattr(member, "key", "")),
        _text(getattr(member, "label", "")),
    }
    return wanted in {value.casefold() for value in values if value}


def _requirements(payload: dict[str, object]) -> list[dict[str, str]]:
    raw = payload.get("requirements")
    if not isinstance(raw, list):
        raw = []
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        product = _text(
            item.get("product") or item.get("product_name")
            or item.get("product_ref")
        )
        if not product:
            continue
        result.append({
            "product": product,
            "frequency": _frequency_name(
                item.get("frequency") or item.get("freq")
            ),
            "data_source": _text(
                item.get("data_source") or item.get("source")
            ),
        })
    if result:
        return result
    products = _normalise_list(payload.get("products"))
    frequencies = _normalise_list(payload.get("frequencies"))
    default_frequency = _frequency_name(frequencies[0]) if frequencies else ""
    source = _text(payload.get("data_source") or payload.get("source"))
    return [{
        "product": product,
        "frequency": default_frequency,
        "data_source": source,
    } for product in products]


def _requirement_matches(
    declarations: tuple[Any, ...],
    product: Any,
    requirement: dict[str, str],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    requested_frequency = requirement.get("frequency", "")
    requested_source = requirement.get("data_source", "")
    for declaration in declarations:
        for member in declaration.members:
            if not _source_matches(declaration, member, requested_source):
                continue
            if not member.has_available_data(product):
                continue
            available_frequency = _frequency_name(
                getattr(member, "frequency", "")
            )
            if not _frequency_compatible(
                available_frequency, requested_frequency,
            ):
                continue
            result.append({
                "source_id": _text(getattr(declaration, "key", "")),
                "source_name": _text(getattr(declaration, "label", "")),
                "member_id": _text(getattr(member, "key", "")),
                "member_label": _text(getattr(member, "label", "")),
                "frequency": available_frequency,
            })
    return result


def capability_snapshot(payload: dict[str, object] | None = None) -> dict[str, object]:
    """Return a JSON-safe local capability snapshot.

    ``summary`` keeps the response small for the source-provider overlay.
    Passing ``requirements`` returns exact product/frequency matches and is
    used by the Manager's preflight route selection.
    """
    value = payload if isinstance(payload, dict) else {}
    declarations, products = _load_catalog()
    requested_products = _normalise_list(value.get("products"))
    requirements = _requirements(value)
    requested_products.extend(item["product"] for item in requirements)
    requested_names, resolved_products = _resolve_products(
        products, requested_products,
    )
    include_products = bool(value.get("include_products"))
    sources = [
        _source_summary(
            declaration, products, include_products=include_products,
        )
        for declaration in declarations
    ]
    checks: list[dict[str, object]] = []
    by_name = {
        _product_name(product): product for product in resolved_products
    }
    for requirement in requirements:
        product = by_name.get(requirement["product"])
        matches = (
            _requirement_matches(declarations, product, requirement)
            if product is not None else []
        )
        checks.append({
            **requirement,
            "matched": bool(matches),
            "providers": matches,
            "reason": (
                "product_not_found" if product is None
                else "no_source_or_frequency" if not matches else ""
            ),
        })
    stable = {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "sources": sources,
        "products": sorted(requested_names),
    }
    revision = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        **stable,
        "revision": revision,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "requirements": checks,
        "all_requirements_matched": all(
            bool(item.get("matched")) for item in checks
        ),
    }

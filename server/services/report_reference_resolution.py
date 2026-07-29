"""Resolve typed report references from authoritative registered objects."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tools.products.classifier_paths import (
    classifier_class_path,
    classifier_object_path,
)
from tools.products.product_utils import product_display_name


def resolve_report_reference(
    *,
    kind: str,
    target: str,
    products: Iterable[Any],
    contracts: Iterable[Any],
) -> dict[str, Any]:
    """Resolve one exact object; never infer a product code or category."""
    if kind != "product":
        raise ValueError(f"unsupported report reference kind: {kind}")
    product = _resolve_registered_product(target, products)
    entity_path = classifier_object_path(product)
    display = product_display_name(product)
    description = str(display["desc"])
    product_class = type(product)
    return {
        "kind": "product",
        "target_ref": entity_path,
        "label": description,
        "object": {
            "canonical_name": str(display["name"]),
            "description": description,
            "python_class": (
                f"{product_class.__module__}.{product_class.__qualname__}"
            ),
            "class_path": classifier_class_path(product_class),
            "entity_path": entity_path,
        },
    }


def _resolve_registered_product(
    target: str, products: Iterable[Any],
) -> Any:
    normalized = str(target).strip()
    if not normalized:
        raise ValueError("report reference target is required")
    matches = []
    for product in products:
        identities = {
            str(getattr(product, "name", "")),
            str(getattr(product, "alias", "")),
            classifier_object_path(product),
        }
        if normalized in identities:
            matches.append(product)
    unique = {id(product): product for product in matches}
    if len(unique) != 1:
        raise LookupError(
            f"registered product does not resolve uniquely: {normalized}"
        )
    return next(iter(unique.values()))

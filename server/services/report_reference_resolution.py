"""Validate Agent-authored typed references against registered product objects."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tools.products.classifier_paths import (
    classifier_class_path,
    classifier_object_path,
    classifier_series_path,
    resolve_classifier_object_path,
    resolve_classifier_series_path,
)
from tools.products.product_utils import product_display_name


def validate_report_reference(
    *,
    kind: str,
    target_ref: str,
    products: Iterable[Any],
    contracts: Iterable[Any],
) -> dict[str, Any]:
    """Validate one exact path; never resolve an alias, code, or display name."""
    if kind == "product":
        return _product_reference(
            kind=kind,
            target_ref=target_ref,
            product=resolve_classifier_object_path(target_ref, products),
        )
    if kind == "contract":
        return _product_reference(
            kind=kind,
            target_ref=target_ref,
            product=resolve_classifier_object_path(target_ref, contracts),
            qualify_name=True,
        )
    if kind == "continuous_contract":
        series = resolve_classifier_series_path(target_ref, products)
        product = series.product
        display = product_display_name(product)
        return {
            "kind": kind,
            "target_ref": target_ref,
            "label": f"{display['desc']} · {series.label}",
            "object": {
                "canonical_name": str(display["name"]),
                "description": str(display["desc"]),
                "entity_path": classifier_series_path(series),
                "product_path": classifier_object_path(product),
                "variant": str(series.variant),
                "backing_product_name": str(series.backing_product_name),
                "adjusted": bool(series.adjusted),
            },
        }
    raise ValueError(f"unsupported report reference kind: {kind}")


def _product_reference(
    *,
    kind: str,
    target_ref: str,
    product: Any,
    qualify_name: bool = False,
) -> dict[str, Any]:
    entity_path = classifier_object_path(product)
    display = product_display_name(product)
    description = str(display["desc"])
    canonical_name = str(display["name"])
    product_class = type(product)
    label = (
        f"{description} · {canonical_name}"
        if qualify_name and description != canonical_name
        else description
    )
    return {
        "kind": kind,
        "target_ref": target_ref,
        "label": label,
        "object": {
            "canonical_name": canonical_name,
            "description": description,
            "python_class": (
                f"{product_class.__module__}.{product_class.__qualname__}"
            ),
            "class_path": classifier_class_path(product_class),
            "entity_path": entity_path,
        },
    }

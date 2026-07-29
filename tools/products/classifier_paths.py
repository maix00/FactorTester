"""Canonical object paths derived from the product classifier class tree."""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.products.Product import Product


OBJECTS_SEGMENT = "_products"
SERIES_SEGMENT = "_series"
_PYTHON_CLASS_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def classifier_object_path(product: Product) -> str:
    """Return the classifier path for one concrete registered product object."""
    from tools.products.Product import Product

    if not isinstance(product, Product):
        raise TypeError("classifier object path requires a Product")
    name = str(getattr(product, "name", ""))
    if not name or any(character in name for character in "/\\\r\n"):
        raise ValueError("product name cannot be represented in a classifier path")
    return f"{classifier_class_path(type(product))}/{OBJECTS_SEGMENT}/{name}"


def classifier_class_path(product_class: type[Product]) -> str:
    """Return only visible Python Product classes from the classifier lineage."""
    from tools.products.Product import Product

    if not isinstance(product_class, type) or not issubclass(
        product_class, Product
    ):
        raise TypeError("classifier class path requires a Product class")
    classes = [
        candidate.__name__
        for candidate in reversed(product_class.__mro__)
        if (
            isinstance(candidate, type)
            and issubclass(candidate, Product)
            and not candidate.__dict__.get(
                "_is_hidden_product_tree_class", False
            )
        )
    ]
    return "/".join(classes)


def resolve_classifier_object_path(
    path: str, products: Iterable[Product],
) -> Product:
    """Resolve an exact canonical path without inferring codes or categories."""
    matches = [
        product
        for product in products
        if classifier_object_path(product) == path
    ]
    if len(matches) != 1:
        raise LookupError(f"classifier object path does not resolve uniquely: {path}")
    return matches[0]


def classifier_series_path(series: object) -> str:
    """Return the classifier's virtual child path for one product series."""
    product = getattr(series, "product", None)
    variant = str(getattr(series, "variant", ""))
    if _PYTHON_CLASS_SEGMENT.fullmatch(variant) is None:
        raise ValueError("product series variant is invalid")
    return f"{classifier_object_path(product)}/{SERIES_SEGMENT}/{variant}"


def resolve_classifier_series_path(
    path: str, products: Iterable[Product],
) -> object:
    """Resolve one exact registered series path without choosing a variant."""
    parse_classifier_series_path(path)
    matches = [
        series
        for product in products
        for series in product.get_series_variants()
        if classifier_series_path(series) == path
    ]
    if len(matches) != 1:
        raise LookupError(
            f"classifier series path does not resolve uniquely: {path}"
        )
    return matches[0]


def parse_classifier_object_path(path: str) -> tuple[tuple[str, ...], str]:
    """Parse the class-only shape; exact object resolution remains authoritative."""
    if not isinstance(path, str):
        raise ValueError("classifier object path must be a string")
    parts = path.split("/")
    class_parts = parts[:-2]
    object_name = parts[-1] if parts else ""
    if (
        len(parts) < 3
        or parts[-2] != OBJECTS_SEGMENT
        or not object_name
        or any(character.isspace() or character == "\\" for character in object_name)
        or not class_parts
        or class_parts[0] != "Product"
        or any(
            _PYTHON_CLASS_SEGMENT.fullmatch(segment) is None
            for segment in class_parts
        )
    ):
        raise ValueError("classifier object path is invalid")
    return tuple(class_parts), object_name


def parse_classifier_series_path(
    path: str,
) -> tuple[tuple[str, ...], str, str]:
    """Parse an exact object path followed by one explicit series variant."""
    if not isinstance(path, str):
        raise ValueError("classifier series path must be a string")
    marker = f"/{SERIES_SEGMENT}/"
    if path.count(marker) != 1:
        raise ValueError("classifier series path is invalid")
    object_path, variant = path.split(marker)
    class_parts, object_name = parse_classifier_object_path(object_path)
    if _PYTHON_CLASS_SEGMENT.fullmatch(variant) is None:
        raise ValueError("classifier series path is invalid")
    return class_parts, object_name, variant

"""Portable syntax checks for exact product-catalog target references.

These checks deliberately know only the public path grammar.  Object existence
and type remain server-owned submission-time validations.
"""

from __future__ import annotations

import re


_CLASS_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OBJECT_MARKER = "_products"
_SERIES_MARKER = "_series"


def parse_classifier_object_path(
    value: str,
) -> tuple[tuple[str, ...], str]:
    """Parse the portable shape without importing the server product tree."""
    validate_product_object_target(value)
    parts = value.split("/")
    return tuple(parts[:-2]), parts[-1]


def validate_product_object_target(value: str) -> None:
    """Reject malformed paths without resolving a product or contract."""
    if not isinstance(value, str):
        raise ValueError("classifier object path must be a string")
    parts = value.split("/")
    class_parts = parts[:-2]
    object_name = parts[-1] if parts else ""
    if (
        len(parts) < 3
        or parts[-2] != _OBJECT_MARKER
        or not object_name
        or any(character.isspace() or character == "\\" for character in object_name)
        or not class_parts
        or class_parts[0] != "Product"
        or any(_CLASS_SEGMENT.fullmatch(item) is None for item in class_parts)
    ):
        raise ValueError("classifier object path is invalid")


def validate_product_series_target(value: str) -> None:
    """Reject malformed series paths without choosing a series variant."""
    if not isinstance(value, str):
        raise ValueError("classifier series path must be a string")
    marker = f"/{_SERIES_MARKER}/"
    if value.count(marker) != 1:
        raise ValueError("classifier series path is invalid")
    product_path, variant = value.split(marker)
    validate_product_object_target(product_path)
    if _CLASS_SEGMENT.fullmatch(variant) is None:
        raise ValueError("classifier series path is invalid")

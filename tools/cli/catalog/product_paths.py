"""Client-safe validation of canonical product object paths."""

from __future__ import annotations

import re


_OBJECTS_SEGMENT = "_products"
_PYTHON_CLASS_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_classifier_object_path(path: str) -> tuple[tuple[str, ...], str]:
    """Validate the path shape without importing the product runtime."""
    if not isinstance(path, str):
        raise ValueError("classifier object path must be a string")
    parts = path.split("/")
    class_parts = parts[:-2]
    object_name = parts[-1] if parts else ""
    if (
        len(parts) < 3
        or parts[-2] != _OBJECTS_SEGMENT
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

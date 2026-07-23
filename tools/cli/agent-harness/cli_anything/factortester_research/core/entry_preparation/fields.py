"""Small field validators shared by Entry authoring modules."""

from __future__ import annotations

import re
from typing import Any


_HAN = re.compile(r"[\u3400-\u9fff]")


def object_field(
    value: dict[str, Any],
    field: str,
    prefix: str,
) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{prefix}.{field} must be an object")
    return item


def text_array(
    value: Any,
    field: str,
    *,
    allow_empty: bool = True,
) -> list[str]:
    if (
        not isinstance(value, list)
        or not all(
            isinstance(item, str) and item.strip() for item in value
        )
        or (not allow_empty and not value)
    ):
        raise ValueError(f"{field} must be a text array")
    return list(dict.fromkeys(value))


def chinese_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or not _HAN.search(text):
        raise ValueError(f"{field} must contain Chinese explanation")
    return text

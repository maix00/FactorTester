"""Product-selection projections for step audit output."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .values import table_from_mappings


def render(field: str, value: Any, *, indent: str) -> list[str] | None:
    if not field.endswith(".product_path_selection") or not isinstance(value, Mapping):
        return None
    paths = [str(item) for item in value.get("selected_paths") or value.get("paths") or []]
    included = [item for item in paths if not item.startswith("-")]
    excluded = [item.removeprefix("-") for item in paths if item.startswith("-")]
    summary = [{
        "id": value.get("product_path_selection_id") or value.get("path_id") or value.get("id"),
        "label": value.get("label") or value.get("product_group"),
        "source": value.get("source_type"),
        "included": len(included),
        "excluded": len(excluded),
    }]
    lines = table_from_mappings(summary, indent=indent)
    if included:
        lines.extend(table_from_mappings(
            ({"op": "+", "path": path} for path in included), indent=indent,
        ))
    if excluded:
        lines.extend(table_from_mappings(
            ({"op": "-", "path": path} for path in excluded), indent=indent,
        ))
    return lines


def render_products_change(field: str, rows: list[Mapping[str, Any]], *, indent: str) -> list[str] | None:
    if not field.endswith(".products"):
        return None
    table_rows = []
    for row in rows:
        after = _product_list(row.get("after"))
        if after is None:
            return None
        table_rows.append({
            "owners": row.get("strategy") or row.get("strategies") or "shared",
            "count": len(after),
            "products": after,
        })
    return table_from_mappings(table_rows, indent=indent)


def render_values(field: str, entries: list[Any], *, indent: str) -> list[str] | None:
    if not field.endswith(".products"):
        return None
    parsed: list[tuple[str, list[str]]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            return None
        products = _product_list(entry.get("value"))
        if products is None:
            return None
        owner = str(entry.get("strategy") or entry.get("strategies") or "shared")
        parsed.append((owner, products))
    groups: dict[tuple[str, ...], list[str]] = {}
    for owner, product_list in parsed:
        groups.setdefault(tuple(product_list), []).append(owner)
    lines: list[str] = []
    for product_list, owners in groups.items():
        lines.extend(table_from_mappings([{
            "owners": ", ".join(owners), "count": len(product_list),
        }], indent=indent))
        lines.extend(table_from_mappings(
            ({"index": index, "product": product} for index, product in enumerate(product_list, start=1)),
            indent=indent,
        ))
    return lines


def _product_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    inner = text[1:-1].strip()
    return [item.strip() for item in inner.split(",") if item.strip()] if inner else []

"""Enumerate only report fields whose strings have rich-text semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComponentText:
    field: str
    value: str
    mode: str


def component_texts(
    *, kind: str, title: str, body: str, content: Any,
) -> list[ComponentText]:
    values = [
        ComponentText("title", title, "inline"),
        ComponentText("body", body, "rich"),
    ]
    if kind == "list" and isinstance(content, dict):
        values += [
            ComponentText(f"content.items[{index}].text", str(item["text"]), "inline")
            for index, item in enumerate(content.get("items") or [])
            if isinstance(item, dict) and "text" in item
        ]
    elif isinstance(content, dict) and {"columns", "rows"} <= set(content):
        values += [
            ComponentText(f"content.columns[{index}]", str(value), "inline")
            for index, value in enumerate(content.get("columns") or [])
        ]
        values += [
            ComponentText(
                f"content.rows[{row_index}][{column_index}]",
                str(value), "inline",
            )
            for row_index, row in enumerate(content.get("rows") or [])
            if isinstance(row, list)
            for column_index, value in enumerate(row)
        ]
    elif kind == "math" and isinstance(content, dict):
        values.append(ComponentText(
            "content.latex", str(content.get("latex") or ""), "latex",
        ))
        values.append(ComponentText(
            "content.fallback", str(content.get("fallback") or ""), "inline",
        ))
    elif isinstance(content, str):
        values.append(ComponentText("content", content, "rich"))
    return [item for item in values if item.value]

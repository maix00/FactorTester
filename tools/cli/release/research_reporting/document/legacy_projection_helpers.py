"""Small deterministic helpers used by legacy content migration."""

from __future__ import annotations

from typing import Any


def block_title(kind: str) -> str:
    return {"paragraph": "正文", "list": "列表"}.get(kind, "报告条目")


def has_component(document: dict[str, Any], value: str) -> bool:
    return any(item.get("component_id") == value for item in document["components"])

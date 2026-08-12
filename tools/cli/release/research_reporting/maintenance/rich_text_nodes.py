"""Node-level helpers for the one-time rich-text migration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..authoring.tree_schema import validate_node
from .rich_text_normalization import normalize_text


def normalize_node(
    node: dict[str, Any], package_root: Path,
) -> tuple[dict[str, Any], list[str]]:
    updated = deepcopy(node)
    body, reasons = normalize_text(
        node["body"], package_root=package_root,
        listify=node["kind"] in {"entry", "special"},
    )
    updated["body"] = body
    content, content_reasons = normalize_content(
        node["content"], package_root=package_root,
    )
    updated["content"] = content
    return validate_node(updated), list(dict.fromkeys([
        *reasons, *content_reasons,
    ]))


def normalize_content(
    value: Any, *, package_root: Path,
) -> tuple[Any, list[str]]:
    if isinstance(value, str):
        return normalize_text(value, package_root=package_root, listify=False)
    if isinstance(value, list):
        result, reasons = [], []
        for item in value:
            normalized, item_reasons = normalize_content(
                item, package_root=package_root,
            )
            result.append(normalized)
            reasons.extend(item_reasons)
        return result, reasons
    if isinstance(value, dict):
        result, reasons = {}, []
        for key, item in value.items():
            if key in {"code", "latex", "asset_ref", "local_ref", "external_ref"}:
                result[key] = item
                continue
            normalized, item_reasons = normalize_content(
                item, package_root=package_root,
            )
            result[key] = normalized
            reasons.extend(item_reasons)
        return result, reasons
    return value, []

"""Deterministic Markdown renderer for the generic report document."""

from __future__ import annotations

from typing import Any

from .model import validate_document


_LEVELS = {
    "chapter": 1,
    "section": 2,
    "subsection": 3,
    "entry": 4,
    "special": 4,
    "table": 4,
    "image": 4,
}


def render_markdown(document: dict[str, Any]) -> bytes:
    value = validate_document(document)
    components = value["components"]
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for item in components:
        by_parent.setdefault(item["parent_id"], []).append(item)
    assets = {item["asset_ref"]: item for item in value["assets"]}
    lines = [f"# {value['title']}", ""]
    _render_children(lines, by_parent, assets, None, 0)
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _render_children(
    lines: list[str], by_parent: dict[str | None, list[dict[str, Any]]],
    assets: dict[str, dict[str, Any]], parent_id: str | None, depth: int,
) -> None:
    for component in by_parent.get(parent_id, []):
        kind = component["kind"]
        # The component kind already encodes the semantic depth. Parent
        # nesting only indents entry-like children; chapters and sections
        # retain stable heading levels across documents.
        level = min(6, _LEVELS[kind] + (min(depth, 2) if kind in {"entry", "special", "table", "image"} else 0))
        lines.extend([f"{'#' * level} {component['title']}", ""])
        body = component.get("body") or ""
        if body:
            lines.extend([body, ""])
        content = component.get("content")
        if kind == "table":
            _table(lines, content)
        elif kind == "image":
            _image(lines, content, assets)
        elif kind == "special":
            label = component.get("display_kind") or "special"
            lines.extend([f"> {label}", ""])
            if content is not None:
                lines.extend([f"```json", _json(content), "```", ""])
        elif content is not None and kind == "entry":
            lines.extend([str(content), ""])
        _render_children(
            lines, by_parent, assets, component["component_id"], depth + 1,
        )


def _table(lines: list[str], content: Any) -> None:
    if not isinstance(content, dict):
        return
    columns = [str(item) for item in content.get("columns") or []]
    rows = content.get("rows") or []
    if not columns:
        return
    lines.extend([
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ])
    lines.extend(
        "| " + " | ".join(str(cell) for cell in row) + " |"
        for row in rows
    )
    lines.append("")


def _image(lines: list[str], content: Any, assets: dict[str, dict[str, Any]]) -> None:
    if not isinstance(content, dict):
        return
    asset = assets.get(str(content.get("asset_ref") or ""))
    if asset is None:
        lines.extend(["- 图像生成物缺失", ""])
        return
    filename = asset["filename"]
    alt = asset.get("alt_text") or asset.get("caption") or "研究图像"
    lines.extend([f"![{alt}](assets/{filename})", ""])


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)

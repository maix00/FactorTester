"""Deterministic Markdown projection of the current persistent report tree."""

from __future__ import annotations

import json
from typing import Any


_LEVELS = {
    "chapter": 1, "section": 2, "subsection": 3, "entry": 4,
    "special": 4, "table": 4, "image": 4, "code": 4, "math": 4,
    "result": 4,
}


def render_tree_markdown(
    snapshot: dict[str, Any], *, image_prefix: str = "../../",
) -> bytes:
    components = list(snapshot["components"])
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for component in components:
        by_parent.setdefault(component["parent_id"], []).append(component)
    assets = {item["asset_ref"]: item for item in snapshot["head"]["assets"]}
    lines = [f"# {snapshot['head']['title']}", ""]
    _render_children(lines, by_parent, assets, None, 0, image_prefix)
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _render_children(lines: list[str], children: dict[str | None, list[dict[str, Any]]], assets: dict[str, dict[str, Any]], parent: str | None, depth: int, image_prefix: str) -> None:
    for item in children.get(parent, []):
        level = min(6, _LEVELS[item["kind"]] + min(depth, 2))
        lines.extend(["#" * level + " " + item["title"], ""])
        if item["body"]:
            lines.extend([item["body"], ""])
        _render_content(lines, item, assets, image_prefix)
        _render_children(lines, children, assets, item["component_id"], depth + 1, image_prefix)


def _render_content(lines: list[str], item: dict[str, Any], assets: dict[str, dict[str, Any]], image_prefix: str) -> None:
    content = item.get("content")
    kind = item["kind"]
    if kind == "table" and isinstance(content, dict):
        columns = [str(value) for value in content.get("columns") or []]
        rows = content.get("rows") or []
        if columns:
            lines.extend(["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
            lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
            lines.append("")
    elif kind == "image" and isinstance(content, dict):
        asset = assets.get(str(content.get("asset_ref") or ""))
        if asset is None:
            lines.extend(["- 图像生成物缺失", ""])
        else:
            alt = asset.get("alt_text") or asset.get("caption") or "研究图像"
            target = asset.get("local_ref") or f"assets/{asset['filename']}"
            lines.extend([f"![{alt}]({image_prefix}{target})", ""])
    elif kind == "code" and isinstance(content, dict):
        source = str(content.get("code") or "")
        fence = "```"
        while fence in source:
            fence += "`"
        lines.extend([f"{fence}{content.get('language') or 'text'}", source, fence, ""])
    elif kind == "math" and isinstance(content, dict):
        lines.extend(["$$", str(content.get("latex") or ""), "$$", ""])
        if content.get("fallback"):
            lines.extend([str(content["fallback"]), ""])
    elif kind in {"result", "special"} and content is not None:
        lines.extend(["```json", json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True), "```", ""])
    elif kind == "entry" and content is not None:
        lines.extend([str(content), ""])

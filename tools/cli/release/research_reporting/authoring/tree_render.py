"""Deterministic Markdown projection of the current persistent report tree."""

from __future__ import annotations

import json
from typing import Any


def render_report_markdown(
    document: dict[str, Any], *, image_prefix: str = "../../",
    front_matter: list[str] | None = None,
) -> bytes:
    """Render a report document as Markdown.

    A server-held tree snapshot carries ``head`` (title + assets); the Web and
    publication projections the manager already serves expose ``title`` and
    ``assets`` beside ``components`` instead.  Both describe the same tree, so
    one renderer serves the server tree, a client copy and a publication.

    ``front_matter`` lines (the branch/author/version block of a download) are
    written directly below the report title.
    """
    if "head" not in document:
        document = {
            "head": {
                "title": str(document.get("title") or ""),
                "report_id": str(document.get("report_id") or ""),
                "assets": list(document.get("assets") or []),
            },
            "components": list(document.get("components") or []),
        }
    return render_tree_markdown(
        document, image_prefix=image_prefix, front_matter=front_matter,
    )


def render_tree_markdown(
    snapshot: dict[str, Any], *, image_prefix: str = "../../",
    front_matter: list[str] | None = None,
) -> bytes:
    components = list(snapshot.get("components") or [])
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for component in components:
        by_parent.setdefault(component.get("parent_id"), []).append(component)
    head = snapshot.get("head") or {}
    assets = {
        str(item.get("asset_ref")): item
        for item in head.get("assets") or [] if item.get("asset_ref")
    }
    lines = [f"# {head.get('title') or ''}", ""]
    for line in front_matter or []:
        lines.extend([line, ""])
    _render_children(lines, by_parent, assets, None, 0, image_prefix)
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _render_children(lines: list[str], children: dict[str | None, list[dict[str, Any]]], assets: dict[str, dict[str, Any]], parent: str | None, depth: int, image_prefix: str) -> None:
    for item in children.get(parent, []):
        # Heading hierarchy comes from ancestry, never from a special kind.
        # Markdown has six heading levels; deeper nodes remain in tree order.
        level = min(6, depth + 1)
        if item.get("title"):
            lines.extend(["#" * level + " " + str(item["title"]), ""])
        if item.get("body"):
            lines.extend([str(item["body"]), ""])
        _render_content(lines, item, assets, image_prefix)
        _render_children(lines, children, assets, item.get("component_id"), depth + 1, image_prefix)


def _render_content(lines: list[str], item: dict[str, Any], assets: dict[str, dict[str, Any]], image_prefix: str) -> None:
    content = item.get("content")
    kind = str(item.get("kind") or "")
    if kind == "list" and isinstance(content, dict):
        _render_list(lines, content)
    elif isinstance(content, dict) and {"columns", "rows"}.issubset(content):
        _render_table(lines, content)
    elif isinstance(content, dict) and content.get("asset_ref"):
        _render_image(lines, content, assets, image_prefix)
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


def _render_list(lines: list[str], content: dict[str, Any]) -> None:
    ordered = content.get("style") == "ordered"
    index = 0
    for item in content.get("items") or []:
        depth = int(item.get("depth") or 0)
        index = index + 1 if depth == 0 else index
        marker = f"{index}." if ordered else "-"
        lines.append(f"{'  ' * depth}{marker} {item.get('text') or ''}")
    lines.append("")


def _render_table(lines: list[str], content: dict[str, Any]) -> None:
    columns = [_table_cell(value) for value in content.get("columns") or []]
    rows = content.get("rows") or []
    if columns:
        lines.extend(["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
        lines.extend(
            "| " + " | ".join(_table_cell(value) for value in row) + " |"
            for row in rows
        )
        lines.append("")


def _table_cell(value: Any) -> str:
    """Keep one typed cell in one Markdown column in the derived view."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _render_image(
    lines: list[str], content: dict[str, Any], assets: dict[str, dict[str, Any]],
    image_prefix: str,
) -> None:
    asset = assets.get(str(content.get("asset_ref") or ""))
    if asset is None:
        lines.extend(["- 图像生成物缺失", ""])
        return
    alt = asset.get("alt_text") or asset.get("caption") or "研究图像"
    external = asset.get("external_ref")
    target = str(external) if external else image_prefix + str(asset.get("local_ref") or f"assets/{asset['filename']}")
    lines.extend([f"![{alt}]({target})", ""])

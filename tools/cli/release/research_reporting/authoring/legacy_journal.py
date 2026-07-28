"""One-shot projection of retired branch journals into report-tree operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .legacy_journal_links import append_chip, component_id, link_chips, selected_chips


def journal_operations(
    path: Path, *, existing_ids: set[str], existing_bindings: set[str],
    existing_assets: set[str],
) -> list[dict[str, Any]]:
    """Convert a physical legacy ``JOURNAL.json`` without retaining it."""
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取旧报告 Journal: {path}") from exc
    checkpoints = journal.get("checkpoints") if isinstance(journal, dict) else None
    if not isinstance(checkpoints, list):
        raise ValueError("旧报告 Journal 缺少 checkpoints")
    operations: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        _checkpoint(
            operations, checkpoint, existing_ids, existing_bindings, existing_assets,
        )
    return operations


def _checkpoint(
    operations: list[dict[str, Any]], checkpoint: Any, ids: set[str],
    bindings: set[str], assets: set[str],
) -> None:
    if not isinstance(checkpoint, dict):
        raise ValueError("旧报告 checkpoint 无效")
    ref = str(checkpoint.get("checkpoint_ref") or "")
    if not ref:
        raise ValueError("旧报告 checkpoint 缺少引用")
    chapter = component_id("legacy-checkpoint", ref)
    _add(
        operations, ids, chapter, "chapter", f"历史检查点 {ref}", None, "", None,
        "", link_chips(checkpoint, chapter, bindings, include_checkpoint=True),
    )
    for index, section in enumerate(checkpoint.get("sections") or []):
        _section(operations, checkpoint, section, index, chapter, ids, bindings, assets)


def _section(
    operations: list[dict[str, Any]], checkpoint: dict[str, Any], section: Any,
    index: int, chapter: str, ids: set[str], bindings: set[str], assets: set[str],
) -> None:
    if not isinstance(section, dict):
        raise ValueError("旧报告 section 无效")
    identity = f"{checkpoint.get('checkpoint_ref')}:{section.get('section_id') or index}"
    section_id = component_id("legacy-section", identity)
    _add(
        operations, ids, section_id, "section", str(section.get("title") or "历史报告章节"),
        chapter, str(section.get("body") or ""), None, "",
        link_chips(section, section_id, bindings),
    )
    for asset_ref in section.get("asset_refs") or []:
        append_chip(operations, section_id, bindings, "artifact", str(asset_ref), "历史生成物", {})
    links = section.get("links") or []
    for block_index, block in enumerate(section.get("blocks") or []):
        _block(operations, block, block_index, section_id, links, ids, bindings, assets)


def _block(
    operations: list[dict[str, Any]], block: Any, index: int, parent: str,
    links: list[Any], ids: set[str], bindings: set[str], assets: set[str],
) -> None:
    if not isinstance(block, dict):
        raise ValueError("旧报告 block 无效")
    kind = str(block.get("kind") or "paragraph")
    component = component_id("legacy-block", parent, str(index))
    chips = selected_chips(block, links, component, bindings)
    if kind == "table":
        content = {"columns": block.get("columns") or [], "rows": [item.get("cells") or [] for item in block.get("rows") or [] if isinstance(item, dict)]}
        _add(operations, ids, component, "table", "表格", parent, "", content, "", chips)
    elif kind == "figure":
        asset = _asset(block.get("asset"), assets, operations)
        _add(operations, ids, component, "image", asset["caption"] or "图像", parent, "", {"asset_ref": asset["asset_ref"]}, "", chips)
    elif kind == "math":
        _add(operations, ids, component, "math", "行间数学公式", parent, "", {"latex": str(block.get("latex") or ""), "fallback": str(block.get("fallback") or "")}, "", chips)
    elif kind in {"obligation_change", "obligation-change", "graph_continuation", "graph-continuation"}:
        _add(operations, ids, component, "special", "义务变化" if "obligation" in kind else "研究图继续", parent, "", block, kind.replace("-", "_"), chips)
    else:
        body = "\n".join(f"- {item.get('text', '')}" for item in block.get("rows") or [] if isinstance(item, dict)) if kind == "list" else str(block.get("text") or "")
        _add(operations, ids, component, "entry", "列表" if kind == "list" else "正文", parent, body, None, "", chips)


def _asset(value: Any, assets: set[str], operations: list[dict[str, Any]]) -> dict[str, str]:
    asset = value if isinstance(value, dict) else {}
    ref = str(asset.get("asset_ref") or "")
    if not ref:
        raise ValueError("旧报告 figure 缺少 asset_ref")
    result = {"asset_ref": ref, "media_type": str(asset.get("media_type") or "application/octet-stream"), "filename": str(asset.get("filename") or ref.replace(":", "_") + ".bin"), "caption": str(asset.get("caption") or ""), "alt_text": str(asset.get("alt_text") or "")}
    if ref not in assets:
        operations.append({"op": "asset", "asset": result})
        assets.add(ref)
    return result


def _add(operations: list[dict[str, Any]], ids: set[str], component: str, kind: str, title: str, parent: str | None, body: str, content: Any, display: str, chips: list[dict[str, Any]]) -> None:
    if component not in ids:
        operations.append({"op": "add", "component_id": component, "kind": kind, "title": title, "parent_id": parent, "body": body, "content": content, "display_kind": display, "bindings": chips})
        ids.add(component)

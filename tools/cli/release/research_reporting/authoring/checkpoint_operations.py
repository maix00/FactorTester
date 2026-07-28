"""Convert one validated checkpoint snapshot into additive report-tree ops."""

from __future__ import annotations

import hashlib
from typing import Any

from .tree_schema import BINDING_KINDS


def checkpoint_operations(
    snapshot: dict[str, Any], *, parent_id: str, existing_ids: set[str],
    existing_bindings: set[str], existing_assets: set[str],
) -> list[dict[str, Any]]:
    """Preserve report semantics without retaining a second Journal document."""
    operations = _assets(snapshot.get("assets") or [], existing_assets)
    for index, section in enumerate(snapshot.get("sections") or []):
        if not isinstance(section, dict):
            raise ValueError("checkpoint report section is invalid")
        section_id = _identity("checkpoint-section", str(section.get("section_id") or index))
        chips = _chips(section.get("links") or [], section_id, existing_bindings)
        _add(
            operations, existing_ids, section_id, "section",
            str(section.get("title") or "研究条目"), parent_id,
            str(section.get("body") or ""), None, "", chips,
        )
        for block_index, block in enumerate(section.get("blocks") or []):
            _block(
                operations, block, section_id, block_index, section.get("links") or [],
                existing_ids, existing_bindings,
            )
    _gaps(operations, snapshot.get("gaps") or [], parent_id, existing_ids)
    return operations


def _assets(values: list[Any], existing: set[str]) -> list[dict[str, Any]]:
    operations = []
    fields = {"asset_ref", "media_type", "filename", "caption", "alt_text"}
    for item in values:
        if not isinstance(item, dict) or not fields.issubset(item):
            raise ValueError("checkpoint report asset is invalid")
        asset = {field: str(item[field]) for field in fields}
        if asset["asset_ref"] not in existing:
            operations.append({"op": "asset", "asset": asset})
            existing.add(asset["asset_ref"])
    return operations


def _block(
    operations: list[dict[str, Any]], block: Any, parent_id: str, index: int,
    links: list[Any], existing_ids: set[str], existing_bindings: set[str],
) -> None:
    if not isinstance(block, dict):
        raise ValueError("checkpoint report block is invalid")
    kind = str(block.get("kind") or "paragraph")
    component_id = _identity("checkpoint-block", parent_id, str(index))
    chips = _chips(_block_links(block, links), component_id, existing_bindings)
    chips.extend(_report_chips(block, component_id, existing_bindings))
    if kind == "table":
        content = {"columns": block.get("columns") or [], "rows": [
            item.get("cells") or [] for item in block.get("rows") or [] if isinstance(item, dict)
        ]}
        _add(operations, existing_ids, component_id, "table", "表格", parent_id, "", content, "", chips)
    elif kind == "figure":
        asset = block.get("asset") or {}
        _add(operations, existing_ids, component_id, "image", str(asset.get("caption") or "图像"), parent_id, "", {"asset_ref": asset.get("asset_ref")}, "", chips)
    elif kind == "math":
        content = {"latex": str(block.get("latex") or ""), "fallback": str(block.get("fallback") or "")}
        _add(operations, existing_ids, component_id, "math", "行间数学公式", parent_id, "", content, "", chips)
    else:
        _add(operations, existing_ids, component_id, "entry", _title(kind), parent_id, _body(kind, block), None, "", chips)


def _chips(links: list[Any], component_id: str, existing: set[str]) -> list[dict[str, Any]]:
    result = []
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            continue
        kind, target = str(link.get("kind") or ""), str(link.get("target_ref") or "")
        if kind not in BINDING_KINDS or not target:
            raise ValueError("checkpoint report link is invalid")
        binding_id = _identity("checkpoint-link", component_id, str(index), target)
        if binding_id not in existing:
            existing.add(binding_id)
            result.append({"binding_id": binding_id, "kind": kind, "target_ref": target, "label": str(link.get("label") or ""), "data": {"link_id": str(link.get("link_id") or "")}})
    return result


def _block_links(block: dict[str, Any], links: list[Any]) -> list[Any]:
    selected = set(block.get("link_ids") or [])
    return [item for item in links if isinstance(item, dict) and item.get("link_id") in selected]


def _report_chips(block: dict[str, Any], component_id: str, existing: set[str]) -> list[dict[str, Any]]:
    binding = block.get("report_binding")
    if not isinstance(binding, dict) or not binding.get("report_requirement_id"):
        return []
    target = str(binding["report_requirement_id"])
    binding_id = _identity("report-requirement", component_id, target)
    if binding_id in existing:
        return []
    existing.add(binding_id)
    return [{"binding_id": binding_id, "kind": "report_requirement", "target_ref": target, "label": "报告义务", "data": {key: str(value) for key, value in binding.items()}}]


def _gaps(operations: list[dict[str, Any]], values: list[Any], parent_id: str, existing_ids: set[str]) -> None:
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError("checkpoint report gap is invalid")
        component_id = _identity("checkpoint-gap", str(index), str(item.get("gap_ref") or ""))
        _add(operations, existing_ids, component_id, "special", "研究缺口", parent_id, "", {"reason": str(item.get("reason") or "")}, "research_gap", [])


def _add(operations: list[dict[str, Any]], existing: set[str], component_id: str, kind: str, title: str, parent_id: str | None, body: str, content: Any, display: str, chips: list[dict[str, Any]]) -> None:
    if component_id in existing:
        operations.extend({"op": "chip", "component_id": component_id, "binding": chip} for chip in chips)
        return
    operations.append({"op": "add", "component_id": component_id, "kind": kind, "title": title, "parent_id": parent_id, "body": body, "content": content, "display_kind": display, "bindings": chips})
    existing.add(component_id)


def _identity(*parts: str) -> str:
    return "cp-" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:48]


def _body(kind: str, block: dict[str, Any]) -> str:
    if kind == "list":
        return "\n".join(f"- {item.get('text', '')}" for item in block.get("rows") or [] if isinstance(item, dict))
    return str(block.get("text") or "")


def _title(kind: str) -> str:
    return {"paragraph": "正文", "list": "列表"}.get(kind, "报告条目")

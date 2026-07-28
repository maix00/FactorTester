"""Convert one validated checkpoint snapshot into additive report-tree ops."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from .operation_presence import OperationPresence
from .tree_schema import BINDING_KINDS


def checkpoint_operations(
    snapshot: dict[str, Any], *, parent_id: str,
    component_exists: Callable[[str], bool], binding_exists: Callable[[str], bool],
    asset_exists: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Preserve report semantics without retaining a second Journal document."""
    presence = OperationPresence(
        component_exists=component_exists, binding_exists=binding_exists,
        asset_exists=asset_exists,
    )
    operations = _assets(snapshot.get("assets") or [], presence)
    for index, section in enumerate(snapshot.get("sections") or []):
        if not isinstance(section, dict):
            raise ValueError("checkpoint report section is invalid")
        section_id = _identity("checkpoint-section", str(section.get("section_id") or index))
        chips = _chips(section.get("links") or [], section_id, presence)
        _add(
            operations, presence, section_id, "section",
            str(section.get("title") or "研究条目"), parent_id,
            str(section.get("body") or ""), None, "", chips,
        )
        for block_index, block in enumerate(section.get("blocks") or []):
            _block(
                operations, block, section_id, block_index, section.get("links") or [],
                presence,
            )
    _gaps(operations, snapshot.get("gaps") or [], parent_id, presence)
    return operations


def _assets(values: list[Any], presence: OperationPresence) -> list[dict[str, Any]]:
    operations = []
    fields = {"asset_ref", "media_type", "filename", "caption", "alt_text"}
    for item in values:
        if not isinstance(item, dict) or not fields.issubset(item):
            raise ValueError("checkpoint report asset is invalid")
        asset = {field: str(item[field]) for field in fields}
        if not presence.asset(asset["asset_ref"]):
            operations.append({"op": "asset", "asset": asset})
            presence.add_asset(asset["asset_ref"])
    return operations


def _block(
    operations: list[dict[str, Any]], block: Any, parent_id: str, index: int,
    links: list[Any], presence: OperationPresence,
) -> None:
    if not isinstance(block, dict):
        raise ValueError("checkpoint report block is invalid")
    kind = str(block.get("kind") or "paragraph")
    component_id = _identity("checkpoint-block", parent_id, str(index))
    chips = _chips(_block_links(block, links), component_id, presence)
    chips.extend(_report_chips(block, component_id, presence))
    if kind == "table":
        content = {"columns": block.get("columns") or [], "rows": [
            item.get("cells") or [] for item in block.get("rows") or [] if isinstance(item, dict)
        ]}
        _add(operations, presence, component_id, "table", "表格", parent_id, "", content, "", chips)
    elif kind == "figure":
        asset = block.get("asset") or {}
        _add(operations, presence, component_id, "image", str(asset.get("caption") or "图像"), parent_id, "", {"asset_ref": asset.get("asset_ref")}, "", chips)
    elif kind == "math":
        content = {"latex": str(block.get("latex") or ""), "fallback": str(block.get("fallback") or "")}
        _add(operations, presence, component_id, "math", "行间数学公式", parent_id, "", content, "", chips)
    else:
        _add(operations, presence, component_id, "entry", _title(kind), parent_id, _body(kind, block), None, "", chips)


def _chips(links: list[Any], component_id: str, presence: OperationPresence) -> list[dict[str, Any]]:
    result = []
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            continue
        kind, target = str(link.get("kind") or ""), str(link.get("target_ref") or "")
        if kind not in BINDING_KINDS or not target:
            raise ValueError("checkpoint report link is invalid")
        binding_id = _identity("checkpoint-link", component_id, str(index), target)
        if not presence.binding(binding_id):
            presence.add_binding(binding_id)
            result.append({"binding_id": binding_id, "kind": kind, "target_ref": target, "label": str(link.get("label") or ""), "data": {"link_id": str(link.get("link_id") or "")}})
    return result


def _block_links(block: dict[str, Any], links: list[Any]) -> list[Any]:
    selected = set(block.get("link_ids") or [])
    return [item for item in links if isinstance(item, dict) and item.get("link_id") in selected]


def _report_chips(block: dict[str, Any], component_id: str, presence: OperationPresence) -> list[dict[str, Any]]:
    binding = block.get("report_binding")
    if not isinstance(binding, dict) or not binding.get("report_requirement_id"):
        return []
    target = str(binding["report_requirement_id"])
    binding_id = _identity("report-requirement", component_id, target)
    if presence.binding(binding_id):
        return []
    presence.add_binding(binding_id)
    return [{"binding_id": binding_id, "kind": "report_requirement", "target_ref": target, "label": "报告义务", "data": {key: str(value) for key, value in binding.items()}}]


def _gaps(operations: list[dict[str, Any]], values: list[Any], parent_id: str, presence: OperationPresence) -> None:
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError("checkpoint report gap is invalid")
        component_id = _identity("checkpoint-gap", str(index), str(item.get("gap_ref") or ""))
        _add(operations, presence, component_id, "special", "研究缺口", parent_id, "", {"reason": str(item.get("reason") or "")}, "research_gap", [])


def _add(operations: list[dict[str, Any]], presence: OperationPresence, component_id: str, kind: str, title: str, parent_id: str | None, body: str, content: Any, display: str, chips: list[dict[str, Any]]) -> None:
    if presence.component(component_id):
        operations.extend({"op": "chip", "component_id": component_id, "binding": chip} for chip in chips)
        return
    operations.append({"op": "add", "component_id": component_id, "kind": kind, "title": title, "parent_id": parent_id, "body": body, "content": content, "display_kind": display, "bindings": chips})
    presence.add_component(component_id)


def _identity(*parts: str) -> str:
    return "cp-" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:48]


def _body(kind: str, block: dict[str, Any]) -> str:
    if kind == "list":
        return "\n".join(f"- {item.get('text', '')}" for item in block.get("rows") or [] if isinstance(item, dict))
    return str(block.get("text") or "")


def _title(kind: str) -> str:
    return {"paragraph": "正文", "list": "列表"}.get(kind, "报告条目")

"""Convert one validated checkpoint snapshot into additive report-tree ops."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from .operation_presence import OperationPresence
from .inline_links import typed_link_list
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
        section_links = _links(section.get("links") or [])
        bindings = _bindings(section_links, section_id, presence)
        _add(
            operations, presence, section_id, "section",
            str(section.get("title") or "研究条目"), parent_id,
            _with_links(str(section.get("body") or ""), section_links),
            None, "", bindings,
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
    block_links = _links(_block_links(block, links))
    report_links = _report_links(block)
    all_links = [*block_links, *report_links]
    bindings = _bindings(all_links, component_id, presence)
    if kind == "table":
        content = _table_content(block, links)
        _add(operations, presence, component_id, "table", "表格", parent_id,
             _with_links("", report_links), content, "", bindings)
    elif kind == "figure":
        asset = block.get("asset") or {}
        _add(operations, presence, component_id, "image",
             str(asset.get("caption") or "图像"), parent_id,
             _with_links("", all_links), {"asset_ref": asset.get("asset_ref")},
             "", bindings)
    elif kind == "math":
        content = {"latex": str(block.get("latex") or ""), "fallback": str(block.get("fallback") or "")}
        _add(operations, presence, component_id, "math", "行间数学公式",
             parent_id, _with_links("", all_links), content, "", bindings)
    else:
        _add(operations, presence, component_id, "entry", _title(kind), parent_id,
             _body(kind, block, links, report_links), None, "", bindings)


def _links(values: list[Any]) -> list[dict[str, str]]:
    result = []
    for link in values:
        if not isinstance(link, dict):
            continue
        kind, target = str(link.get("kind") or ""), str(link.get("target_ref") or "")
        if kind not in BINDING_KINDS or not target:
            raise ValueError("checkpoint report link is invalid")
        result.append({
            "kind": kind, "target_ref": target,
            "label": str(link.get("label") or _default_label(kind)),
            "link_id": str(link.get("link_id") or ""),
            "data": {"link_id": str(link.get("link_id") or "")},
        })
    return result


def _bindings(
    links: list[dict[str, str]], component_id: str, presence: OperationPresence,
) -> list[dict[str, Any]]:
    result = []
    for index, link in enumerate(links):
        kind, target = link["kind"], link["target_ref"]
        binding_id = _identity("checkpoint-link", component_id, str(index), target)
        if not presence.binding(binding_id):
            presence.add_binding(binding_id)
            result.append({
                "binding_id": binding_id, "kind": kind, "target_ref": target,
                "label": link["label"], "data": link["data"],
            })
    return result


def _block_links(block: dict[str, Any], links: list[Any]) -> list[Any]:
    selected = set(block.get("link_ids") or [])
    return [item for item in links if isinstance(item, dict) and item.get("link_id") in selected]


def _report_links(block: dict[str, Any]) -> list[dict[str, str]]:
    binding = block.get("report_binding")
    if not isinstance(binding, dict) or not binding.get("report_requirement_id"):
        return []
    target = str(binding["report_requirement_id"])
    return [{
        "kind": "report_requirement", "target_ref": target,
        "label": "报告义务", "link_id": target,
        "data": {key: str(value) for key, value in binding.items()},
    }]


def _gaps(operations: list[dict[str, Any]], values: list[Any], parent_id: str, presence: OperationPresence) -> None:
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError("checkpoint report gap is invalid")
        component_id = _identity("checkpoint-gap", str(index), str(item.get("gap_ref") or ""))
        _add(operations, presence, component_id, "special", "研究缺口", parent_id, "", {"reason": str(item.get("reason") or "")}, "research_gap", [])


def _add(operations: list[dict[str, Any]], presence: OperationPresence, component_id: str, kind: str, title: str, parent_id: str | None, body: str, content: Any, display: str, bindings: list[dict[str, Any]]) -> None:
    if presence.component(component_id):
        operations.extend({"op": "bind", "component_id": component_id, "binding": binding} for binding in bindings)
        return
    operations.append({"op": "add", "component_id": component_id, "kind": kind, "title": title, "parent_id": parent_id, "body": body, "content": content, "display_kind": display, "bindings": bindings})
    presence.add_component(component_id)


def _identity(*parts: str) -> str:
    return "cp-" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:48]


def _body(
    kind: str, block: dict[str, Any], links: list[Any],
    report_links: list[dict[str, str]],
) -> str:
    if kind == "list":
        all_links = _links(links)
        selected = {
            item["link_id"]: item for item in all_links if item["link_id"]
        }
        rows = []
        for item in block.get("rows") or []:
            if not isinstance(item, dict):
                continue
            row_links = [selected[link_id] for link_id in item.get("link_ids") or [] if link_id in selected]
            text = f"- {item.get('text', '')}"
            if row_links:
                text += "\n" + "\n".join("  " + line for line in typed_link_list(row_links).splitlines())
            rows.append(text)
        return _with_links("\n".join(rows), report_links)
    return _with_links(str(block.get("text") or ""), [*_links(links), *report_links])


def _table_content(block: dict[str, Any], links: list[Any]) -> dict[str, list[list[str]] | list[str]]:
    selected = {item["link_id"]: item for item in _links(links) if item["link_id"]}
    source_rows = [item for item in block.get("rows") or [] if isinstance(item, dict)]
    has_links = any(item.get("link_ids") for item in source_rows)
    columns = [str(item) for item in block.get("columns") or []]
    if has_links:
        columns.append("关联")
    rows = []
    for item in source_rows:
        row = [str(value) for value in item.get("cells") or []]
        if has_links:
            row_links = [selected[link_id] for link_id in item.get("link_ids") or [] if link_id in selected]
            row.append(typed_link_list(row_links))
        rows.append(row)
    return {"columns": columns, "rows": rows}


def _with_links(body: str, links: list[dict[str, str]]) -> str:
    rendered = typed_link_list(links)
    if not rendered:
        return body
    return f"{body}\n\n关联：\n{rendered}".strip()


def _default_label(kind: str) -> str:
    return {
        "evidence": "证据", "obligation": "义务", "task": "任务",
        "job": "测试任务", "claim": "主张", "artifact": "生成物",
        "report_requirement": "报告义务", "graph_reference": "研究图",
        "checkpoint": "节点检查", "run": "运行", "run_spec": "运行配置",
        "trial_plan": "试验计划", "delta": "变化",
    }.get(kind, "关联记录")


def _title(kind: str) -> str:
    return {"paragraph": "正文", "list": "列表"}.get(kind, "报告条目")

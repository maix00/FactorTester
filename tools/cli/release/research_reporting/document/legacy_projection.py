"""Project legacy Graph journal fragments into content and bindings."""

from __future__ import annotations

from typing import Any

from .legacy_assets import ensure_asset
from .legacy_links import attach, attach_link, content_hash, safe_id
from .legacy_projection_helpers import block_title, has_component
from .model import add_component


def project_fragment(
    document: dict[str, Any], bindings: dict[str, Any], fragment: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    branch_ref = str(fragment.get("branch_ref") or "legacy")
    checkpoint_ref = str(fragment.get("checkpoint_ref") or "checkpoint")
    graph_ref = str(fragment.get("graph_ref") or "")
    chapter_id = safe_id(f"chapter-{branch_ref}")
    if not has_component(document, chapter_id):
        document = add_component(
            document, component_id=chapter_id, kind="chapter",
            title=f"研究分支 {branch_ref}",
            body="历史报告章节",
        )
        if graph_ref:
            bindings = attach(
                bindings, document, chapter_id, "graph_reference",
                graph_ref if ":" in graph_ref else f"graph:{graph_ref}", graph_ref,
            )
        bindings = attach(
            bindings, document, chapter_id, "checkpoint",
            "trace:" + checkpoint_ref.removeprefix("trace:"), checkpoint_ref,
        )
    migrated = 0
    assets = 0
    for index, section in enumerate(fragment.get("sections") or []):
        if not isinstance(section, dict):
            continue
        section_id = safe_id(
            f"section-{branch_ref}-{checkpoint_ref}-"
            f"{section.get('section_id', index)}-{index}"
        )
        if has_component(document, section_id):
            continue
        document = add_component(
            document, component_id=section_id, kind="section",
            parent_id=chapter_id, title=str(section.get("title") or section_id),
            body=str(section.get("body") or ""),
        )
        for ref in [
            *(fragment.get("evidence_refs") or []),
            *(section.get("evidence_refs") or []),
        ]:
            bindings = attach(bindings, document, section_id, "evidence", str(ref))
        for ref in section.get("asset_refs") or []:
            bindings = attach(bindings, document, section_id, "artifact", str(ref))
        for link in section.get("links") or []:
            if isinstance(link, dict):
                bindings = attach_link(bindings, document, section_id, link)
        for block_index, block in enumerate(section.get("blocks") or []):
            document, bindings, added_asset = _project_block(
                document, bindings, section_id, block, block_index,
                checkpoint_ref, section.get("links") or [],
            )
            assets += added_asset
        migrated += 1
    return document, bindings, migrated, assets


def _project_block(
    document: dict[str, Any], bindings: dict[str, Any], parent_id: str,
    block: Any, index: int, checkpoint_ref: str, section_links: list[Any],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    if not isinstance(block, dict):
        return document, bindings, 0
    kind = str(block.get("kind") or "entry")
    component_id = safe_id(f"entry-{checkpoint_ref}-{parent_id}-{index}")
    if kind == "table":
        content = {
            "columns": block.get("columns") or [],
            "rows": [
                row.get("cells") or [] for row in block.get("rows") or []
                if isinstance(row, dict)
            ],
        }
        document = add_component(
            document, component_id=component_id, kind="table",
            parent_id=parent_id, title="表格", content=content,
        )
        return _attach_block_links(document, bindings, component_id, block, section_links) + (0,)
    if kind == "figure" and isinstance(block.get("asset"), dict):
        asset = dict(block["asset"])
        document = ensure_asset(document, asset)
        document = add_component(
            document, component_id=component_id, kind="image",
            parent_id=parent_id, title=str(asset.get("caption") or "图像"),
            content={"asset_ref": asset.get("asset_ref")},
        )
        return _attach_block_links(document, bindings, component_id, block, section_links) + (1,)
    if kind == "math":
        document = add_component(
            document, component_id=component_id, kind="special",
            parent_id=parent_id, title="行间数学公式", display_kind="display_math",
            content={"latex": block.get("latex") or "", "fallback": block.get("fallback") or ""},
        )
    elif kind in {"obligation_change", "obligation-change"}:
        document = add_component(
            document, component_id=component_id, kind="special",
            parent_id=parent_id, title="义务变化",
            display_kind="obligation_change",
            content=_content_only_special(block),
        )
    elif kind in {"graph_continuation", "graph-continuation"}:
        document = add_component(
            document, component_id=component_id, kind="special",
            parent_id=parent_id, title="研究图继续",
            display_kind="graph_continuation",
            content=_content_only_special(block),
        )
    else:
        content = block.get("rows") if kind == "list" else None
        document = add_component(
            document, component_id=component_id, kind="entry",
            parent_id=parent_id, title=block_title(kind),
            body=str(block.get("text") or ""), content=content,
        )
    return _attach_block_links(document, bindings, component_id, block, section_links) + (0,)


# These keys describe where a legacy block came from or what it is bound to.
# They belong in the sidecar bindings file, never in ReportDocument.content.
_RELATION_KEYS = {
    "report_binding", "link_ids", "links", "graph_ref", "graph_id",
    "branch_ref", "branch_id", "checkpoint_ref", "checkpoint_id",
    "source_branch_ref", "source_graph_ref", "evidence_refs", "asset_refs",
    "job_ref", "task_ref", "obligation_ref", "target_ref", "source_ref",
}


def _content_only_special(value: dict[str, Any]) -> dict[str, Any]:
    """Keep user-facing special-section payload, dropping relation metadata."""
    return _strip_relations(value)


def _strip_relations(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_relations(item)
            for key, item in value.items()
            if str(key) not in _RELATION_KEYS
        }
    if isinstance(value, list):
        return [_strip_relations(item) for item in value]
    return value


def _attach_block_links(
    document: dict[str, Any], bindings: dict[str, Any], component_id: str,
    block: dict[str, Any], section_links: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    link_ids = set(block.get("link_ids") or [])
    for link in section_links:
        if isinstance(link, dict) and link.get("link_id") in link_ids:
            bindings = attach_link(bindings, document, component_id, link)
    for link in block.get("links") or []:
        if isinstance(link, dict):
            bindings = attach_link(bindings, document, component_id, link)
    binding = block.get("report_binding")
    if isinstance(binding, dict):
        target = str(binding.get("report_requirement_id") or "")
        if target:
            bindings = attach(
                bindings, document, component_id, "report_requirement", target,
            )
    return document, bindings

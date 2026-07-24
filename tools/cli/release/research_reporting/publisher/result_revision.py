"""Latest-wins source revision for one authoritative result action."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..journal import content_hash, validate_fragment_sequence

_RESULT_REQUIREMENT = "report.node.trial_execution.action"


def revise_result_items(
    fragments: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace prior result bindings and remove their duplicate source blocks."""
    values = deepcopy(fragments)
    replacements = {
        _binding_key(item): item
        for item in incoming
        if item.get("report_requirement_id") == _RESULT_REQUIREMENT
    }
    occurrences: dict[tuple[str, str], list[tuple[int, int, int]]] = {}
    for fragment_index, fragment in enumerate(values):
        for section_index, section in enumerate(fragment["sections"]):
            for block_index, block in enumerate(section.get("blocks") or []):
                binding = block.get("report_binding")
                if not isinstance(binding, dict):
                    continue
                key = _binding_key(binding)
                if key in replacements:
                    occurrences.setdefault(key, []).append((
                        fragment_index, section_index, block_index,
                    ))
    keep = {key: positions[-1] for key, positions in occurrences.items()}
    changed_checkpoints = set()
    removed = []
    replaced = []
    for fragment_index, fragment in enumerate(values):
        sections = []
        for section_index, section in enumerate(fragment["sections"]):
            blocks = []
            touched = False
            incoming_links: dict[str, dict[str, Any]] = {}
            for block_index, block in enumerate(section.get("blocks") or []):
                binding = block.get("report_binding")
                key = (
                    _binding_key(binding)
                    if isinstance(binding, dict) else None
                )
                if key not in replacements:
                    blocks.append(block)
                    continue
                touched = True
                location = (fragment_index, section_index, block_index)
                if location != keep[key]:
                    removed.append(_item_ref(binding))
                    changed_checkpoints.add(fragment["checkpoint_ref"])
                    continue
                item = replacements[key]
                expected = "report-item:sha256:" + item["item_hash"]
                if binding.get("report_item_ref") == expected:
                    blocks.append(block)
                    continue
                replacement = deepcopy(item["content"])
                replacement["report_binding"] = {
                    "report_requirement_id": item["report_requirement_id"],
                    "subject_ref": item["subject_ref"],
                    "report_item_ref": expected,
                }
                blocks.append(replacement)
                incoming_links.update({
                    link["link_id"]: deepcopy(link)
                    for link in item.get("links") or []
                })
                replaced.append({
                    "before": _item_ref(binding),
                    "after": expected,
                })
                changed_checkpoints.add(fragment["checkpoint_ref"])
                if len(section.get("blocks") or []) == 1:
                    section["title"] = str(
                        item.get("title_zh") or section["title"]
                    )
            if touched:
                section["blocks"] = blocks
                if not blocks:
                    continue
                used = _used_link_ids(blocks)
                links = {
                    link["link_id"]: link
                    for link in section.get("links") or []
                    if link.get("link_id") in used
                }
                links.update({
                    key: value for key, value in incoming_links.items()
                    if key in used
                })
                section["links"] = list(links.values())
            sections.append(section)
        fragment["sections"] = sections
    values = _drop_empty_and_rehash(
        values, changed_checkpoints=changed_checkpoints,
    )
    remaining = {item["checkpoint_ref"] for item in values}
    validate_fragment_sequence(values)
    return values, {
        "schema_version": 1,
        "migration": "result-item-revision-v1",
        "changed": bool(removed or replaced),
        "changed_checkpoint_refs": sorted(changed_checkpoints),
        "removed_checkpoint_refs": sorted(
            item["checkpoint_ref"] for item in fragments
            if item["checkpoint_ref"] not in remaining
        ),
        "removed_item_refs": removed,
        "replaced_item_refs": replaced,
    }


def _drop_empty_and_rehash(
    fragments: list[dict[str, Any]], *, changed_checkpoints: set[str],
) -> list[dict[str, Any]]:
    values = [item for item in fragments if item["sections"]]
    for index, fragment in enumerate(values):
        lineage_changed = (
            index > 0
            and fragment["predecessor_checkpoint_ref"]
            != values[index - 1]["checkpoint_ref"]
        )
        if lineage_changed:
            fragment["predecessor_checkpoint_ref"] = values[
                index - 1
            ]["checkpoint_ref"]
        if (
            fragment["checkpoint_ref"] not in changed_checkpoints
            and not lineage_changed
        ):
            continue
        if fragment["checkpoint_ref"] in changed_checkpoints:
            fragment["narrative_hash"] = content_hash({
                "revision": "result-item-revision-v1",
                "prior_narrative_hash": fragment["narrative_hash"],
                "sections": fragment["sections"],
            })
        fragment.pop("section_hash")
        fragment["section_hash"] = content_hash(fragment)
    return values


def _binding_key(value: dict[str, Any]) -> tuple[str, str]:
    return (
        str(value.get("report_requirement_id") or ""),
        str(value.get("subject_ref") or ""),
    )


def _item_ref(binding: dict[str, Any]) -> str:
    return str(binding.get("report_item_ref") or "")


def _used_link_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        values = set(
            str(item) for item in value.get("link_ids") or []
            if isinstance(item, str)
        )
        for item in value.values():
            values.update(_used_link_ids(item))
        return values
    if isinstance(value, list):
        values = set()
        for item in value:
            values.update(_used_link_ids(item))
        return values
    return set()

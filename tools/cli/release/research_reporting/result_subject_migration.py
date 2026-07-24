"""One-shot normalization of historical result-report Action subjects."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from .journal import content_hash, validate_fragment_sequence
from .publisher.result_revision import revise_result_items
from .report_items import report_fragment_hash, report_item_hash

_REQUIREMENT = "report.node.trial_execution.action"


def migrate_result_action_subjects(
    fragments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return rehashed fragments and an idempotent migration receipt."""
    values = deepcopy(fragments)
    changes = []
    for fragment in values:
        before_hash = fragment["section_hash"]
        before_items = _items(fragment)
        item_changes = []
        for section in fragment["sections"]:
            section_changed = False
            for block in section.get("blocks") or []:
                binding = block.get("report_binding")
                if not isinstance(binding, dict):
                    continue
                before_subject = str(binding.get("subject_ref") or "")
                after_subject = _subject(
                    before_subject,
                    str(binding.get("report_requirement_id") or ""),
                )
                if after_subject == before_subject:
                    continue
                before_item = str(binding.get("report_item_ref") or "")
                binding["subject_ref"] = after_subject
                after_item = _rehash_item(block, binding)
                item_changes.append({
                    "before_subject_ref": before_subject,
                    "after_subject_ref": after_subject,
                    "before_item_ref": before_item,
                    "after_item_ref": after_item,
                })
                section_changed = True
            if section_changed:
                _rehash_section_id(section)
        if not item_changes:
            continue
        after_items = _items(fragment)
        before_fragment = report_fragment_hash(before_items)
        after_fragment = report_fragment_hash(after_items)
        prior_narrative = fragment["narrative_hash"]
        fragment["narrative_hash"] = content_hash({
            "migration": "result-action-subject-v1",
            "prior_narrative_hash": prior_narrative,
            "sections": fragment["sections"],
        })
        fragment.pop("section_hash")
        fragment["section_hash"] = content_hash(fragment)
        changes.append({
            "checkpoint_ref": fragment["checkpoint_ref"],
            "before_section_hash": before_hash,
            "after_section_hash": fragment["section_hash"],
            "before_narrative_hash": prior_narrative,
            "after_narrative_hash": fragment["narrative_hash"],
            "before_report_fragment_ref":
                f"report-fragment:sha256:{before_fragment}",
            "after_report_fragment_ref":
                f"report-fragment:sha256:{after_fragment}",
            "items": item_changes,
        })
    values, deduplication = revise_result_items(
        values, _latest_result_items(values),
    )
    final = {
        item["checkpoint_ref"]: item for item in values
    }
    for change in changes:
        fragment = final.get(change["checkpoint_ref"])
        change["after_section_hash"] = (
            fragment["section_hash"] if fragment else ""
        )
        change["after_narrative_hash"] = (
            fragment["narrative_hash"] if fragment else ""
        )
    validate_fragment_sequence(values)
    changed_checkpoints = {
        item["checkpoint_ref"] for item in changes
    }.union(deduplication["changed_checkpoint_refs"])
    return values, {
        "schema_version": 1,
        "migration": "result-action-subject-v1",
        "changed": bool(changes or deduplication["changed"]),
        "changed_fragment_count": len(changed_checkpoints),
        "changes": changes,
        "deduplication": deduplication,
    }


def _subject(value: str, requirement: str) -> str:
    if requirement != _REQUIREMENT:
        return value
    if value.startswith("audit:"):
        key = value.removeprefix("audit:")
        prefix = "audit:"
    elif value.startswith("action:"):
        key = value
        prefix = ""
    else:
        return value
    while key.startswith("action:"):
        key = key.removeprefix("action:")
    return f"{prefix}{key}" if prefix else f"action:{key}"


def _rehash_item(block, binding):
    content = {
        key: deepcopy(value) for key, value in block.items()
        if key not in {"report_binding", "report_timing"}
    }
    digest = report_item_hash(
        report_requirement_id=str(binding["report_requirement_id"]),
        subject_ref=str(binding["subject_ref"]),
        content_kind=str(block["kind"]),
        content=content,
    )
    binding["report_item_ref"] = f"report-item:sha256:{digest}"
    return binding["report_item_ref"]


def _items(fragment):
    return [
        {
            "report_requirement_id": str(binding["report_requirement_id"]),
            "subject_ref": str(binding["subject_ref"]),
            "content_kind": str(block["kind"]),
            "item_hash": str(binding["report_item_ref"]).removeprefix(
                "report-item:sha256:"
            ),
        }
        for section in fragment["sections"]
        for block in section.get("blocks") or []
        if isinstance((binding := block.get("report_binding")), dict)
    ]


def _rehash_section_id(section):
    items = [
        {
            "report_requirement_id": binding["report_requirement_id"],
            "subject_ref": binding["subject_ref"],
        }
        for block in section.get("blocks") or []
        if isinstance((binding := block.get("report_binding")), dict)
    ]
    if not items or not str(section.get("section_id") or "").startswith(
        "current-node-"
    ):
        return
    stable = hashlib.sha256(json.dumps(
        {"chapter_ref": section.get("chapter_ref"), "items": items},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()[:16]
    section["section_id"] = f"current-node-{stable}"


def _latest_result_items(
    fragments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    values: dict[tuple[str, str], dict[str, Any]] = {}
    for fragment in fragments:
        for section in fragment["sections"]:
            for block in section.get("blocks") or []:
                binding = block.get("report_binding")
                if (
                    not isinstance(binding, dict)
                    or binding.get("report_requirement_id") != _REQUIREMENT
                ):
                    continue
                key = (
                    str(binding["report_requirement_id"]),
                    str(binding["subject_ref"]),
                )
                values[key] = {
                    "report_requirement_id": key[0],
                    "subject_ref": key[1],
                    "item_hash": str(
                        binding["report_item_ref"]
                    ).removeprefix("report-item:sha256:"),
                    "content": {
                        name: deepcopy(value)
                        for name, value in block.items()
                        if name not in {"report_binding", "report_timing"}
                    },
                    "links": deepcopy(section.get("links") or []),
                    "title_zh": str(section.get("title") or ""),
                }
    return list(values.values())

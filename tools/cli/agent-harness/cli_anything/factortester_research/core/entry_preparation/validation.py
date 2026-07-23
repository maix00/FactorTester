"""Deterministic local validation and compact submission projection."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash,
)

from .assessment_validation import validate_assessment
from .fields import text_array
from .report_projection import build_report_items


def validate_entry_assessment_document(
    value: dict[str, Any],
) -> dict[str, Any]:
    """Validate edited authoring data without contacting or mutating a backend."""
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("entry assessment schema_version must be 1")
    selected = text_array(
        value.get("selected_requirement_ids"),
        "selected_requirement_ids",
        allow_empty=False,
    )
    assessments = value.get("assessments")
    if not isinstance(assessments, list):
        raise ValueError("assessments must be an array")
    by_id = {
        str(item.get("requirement_id") or ""): item
        for item in assessments if isinstance(item, dict)
    }
    if len(by_id) != len(assessments) or set(by_id) != set(selected):
        raise ValueError(
            "assessments must exactly cover selected_requirement_ids"
        )
    normalized = []
    local_items = []
    for requirement_id in selected:
        assessment, report_input = validate_assessment(
            by_id[requirement_id],
            factor_facts=value.get("factor_facts"),
        )
        normalized.append(assessment)
        local_items.extend(build_report_items(**report_input))
    report_projection = [
        {
            "report_requirement_id": item["report_requirement_id"],
            "subject_ref": item["subject_ref"],
            "content_kind": item["content_kind"],
            "item_hash": item["item_hash"],
        }
        for item in local_items
    ]
    return {
        "valid": True,
        "context": value.get("context"),
        "entry_requirement_assessments": normalized,
        "report_submission": {
            "schema_version": 1,
            "fragment_hash": report_fragment_hash(report_projection),
            "items": sorted(
                report_projection,
                key=lambda item: (
                    item["report_requirement_id"], item["subject_ref"]
                ),
            ),
        },
        "local_report_items": local_items,
    }

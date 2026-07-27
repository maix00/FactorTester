"""Build the hash-only Graph report submission from a local report document."""

from __future__ import annotations

from typing import Any

from .bindings import validate_bindings
from .validation import validate_document
from ..report_items import report_fragment_hash, report_item_hash


def build_report_submission(
    document: dict[str, Any],
    bindings: dict[str, Any],
) -> dict[str, Any]:
    """Require each report chip to identify its subject and content kind."""
    value = validate_document(document)
    links = validate_bindings(bindings, value)
    components = {
        item["component_id"]: item for item in value["components"]
    }
    items: list[dict[str, str]] = []
    for link in links["bindings"]:
        if link["kind"] != "report_requirement":
            continue
        component = components.get(link["component_id"])
        if component is None:
            raise ValueError("report requirement chip component is missing")
        data = link.get("data") or {}
        subject_ref = str(data.get("subject_ref") or "")
        content_kind = str(data.get("content_kind") or "")
        if not subject_ref or not content_kind:
            raise ValueError(
                "report requirement chip data needs subject_ref and content_kind"
            )
        content = {
            "title": component["title"],
            "body": component["body"],
            "content": component.get("content"),
            "display_kind": component.get("display_kind") or "",
        }
        item = {
            "report_requirement_id": link["target_ref"],
            "subject_ref": subject_ref,
            "content_kind": content_kind,
            "item_hash": report_item_hash(
                report_requirement_id=link["target_ref"],
                subject_ref=subject_ref,
                content_kind=content_kind,
                content=content,
            ),
        }
        items.append(item)
    if not items:
        raise ValueError("report has no report_requirement chips")
    return {
        "schema_version": 1,
        "fragment_hash": report_fragment_hash(items),
        "items": sorted(
            items,
            key=lambda item: (
                item["report_requirement_id"], item["subject_ref"],
            ),
        ),
    }


def merge_report_submissions(
    *submissions: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Combine local report fragments before one node advance."""
    items: dict[tuple[str, str], dict[str, Any]] = {}
    for submission in submissions:
        if submission is None:
            continue
        if (
            not isinstance(submission, dict)
            or submission.get("schema_version") != 1
        ):
            raise ValueError("report submission schema_version must be 1")
        raw_items = submission.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("report submission items must be an array")
        for item in raw_items:
            if not isinstance(item, dict):
                raise ValueError("report submission item must be an object")
            key = (
                str(item.get("report_requirement_id") or ""),
                str(item.get("subject_ref") or ""),
            )
            previous = items.get(key)
            if previous is not None and previous != item:
                raise ValueError(
                    "report submission contains conflicting bindings: "
                    + "@".join(key)
                )
            items[key] = dict(item)
    if not items:
        return None
    ordered = sorted(
        items.values(),
        key=lambda item: (
            str(item.get("report_requirement_id") or ""),
            str(item.get("subject_ref") or ""),
        ),
    )
    return {
        "schema_version": 1,
        "fragment_hash": report_fragment_hash(ordered),
        "items": ordered,
    }

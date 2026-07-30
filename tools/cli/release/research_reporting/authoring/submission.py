"""Hash-only Graph submissions derived from a branch report-tree snapshot."""

from __future__ import annotations

from typing import Any

from ..report_items import report_fragment_hash, report_item_hash


def build_report_submission(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build server-side requirement coverage without uploading report prose."""
    components = {
        item["component_id"]: item for item in snapshot["components"]
    }
    items: list[dict[str, str]] = []
    for link in snapshot["bindings"]:
        if link["kind"] != "report_requirement":
            continue
        component = components.get(link["component_id"])
        if component is None:
            raise ValueError("report requirement binding component is missing")
        data = link.get("data") or {}
        subject_ref = str(data.get("subject_ref") or "")
        content_kind = str(data.get("content_kind") or "")
        if not subject_ref or not content_kind:
            raise ValueError(
                "report requirement binding data needs subject_ref and content_kind"
            )
        content = {
            "title": component["title"],
            "body": component["body"],
            "content": component.get("content"),
            "display_kind": component.get("display_kind") or "",
        }
        items.append({
            "report_requirement_id": link["target_ref"],
            "subject_ref": subject_ref,
            "content_kind": content_kind,
            "item_hash": _binding_item_hash(
                data=data,
                report_requirement_id=link["target_ref"],
                subject_ref=subject_ref,
                content_kind=content_kind,
                content=content,
            ),
        })
    if not items:
        raise ValueError("report has no report_requirement bindings")
    ordered = sorted(
        items,
        key=lambda item: (
            item["report_requirement_id"], item["subject_ref"],
        ),
    )
    return {
        "schema_version": 1,
        "fragment_hash": report_fragment_hash(ordered),
        "items": ordered,
    }


def _binding_item_hash(
    *,
    data: dict[str, Any],
    report_requirement_id: str,
    subject_ref: str,
    content_kind: str,
    content: dict[str, Any],
) -> str:
    """Keep the server-audited hash for a checkpoint-projected report item."""
    report_item_ref = str(data.get("report_item_ref") or "")
    if report_item_ref:
        prefix = "report-item:sha256:"
        digest = report_item_ref.removeprefix(prefix)
        if (
            not report_item_ref.startswith(prefix)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(
                "report requirement binding report_item_ref is invalid"
            )
        return digest
    return report_item_hash(
        report_requirement_id=report_requirement_id,
        subject_ref=subject_ref,
        content_kind=content_kind,
        content=content,
    )


def merge_report_submissions(
    *submissions: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Combine independent local coverage projections for one node advance."""
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

"""Deterministic coverage validation for Graph-declared local report items."""

from __future__ import annotations

import re
from typing import Any

import orjson

from tools.cli.release.research_reporting.report_items import (
    report_fragment_hash,
)


# This is a persisted audit index of required report bindings, not the
# routine Agent context packet. Dense v9 nodes can legitimately bind more
# than twenty compact hash-only items, so keep a separate protocol ceiling.
MAX_REPORT_SUBMISSION_BYTES = 16 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUBJECT_PREFIXES = {
    "current_research_scope": ("node:",),
    "transition_delta": ("graph-edge:",),
    "entry_resolution_frame": ("node:",),
    "verification_obligation": ("obligation:", "requirement:"),
    "graph_version_delta": ("graph-version-delta:",),
    "evidence_envelope": ("evidence:",),
}


def validate_report_submission(
    *,
    graph: dict[str, Any],
    source_node: dict[str, Any],
    edge: dict[str, Any],
    target_node: dict[str, Any],
    entry_assessments: list[dict[str, Any]],
    transition_evidence: dict[str, Any],
    submitted: Any,
    allow_missing: bool = False,
) -> dict[str, Any] | None:
    """Require exact local-report coverage only for enforcing Graph versions."""
    policy = graph.get("report_policy") or {}
    if policy.get("enforcement") != "required":
        if submitted is not None:
            raise ValueError(
                "current Graph does not declare report_submission enforcement"
            )
        return None
    if submitted is None and allow_missing:
        submitted = {
            "schema_version": 1,
            "fragment_hash": report_fragment_hash([]),
            "items": [],
        }
    if not isinstance(submitted, dict):
        raise ValueError("report_submission is required")
    if set(submitted) != {"schema_version", "fragment_hash", "items"}:
        raise ValueError("report_submission fields are invalid")
    if submitted.get("schema_version") != 1:
        raise ValueError("report_submission schema_version must be 1")
    fragment_hash = _hash(submitted.get("fragment_hash"), "fragment_hash")
    expected_bindings = expected_report_bindings(
        graph=graph,
        source_node=source_node,
        edge=edge,
        target_node=target_node,
        entry_assessments=entry_assessments,
        transition_evidence=transition_evidence,
    )
    required = {
        (item["report_requirement_id"], item["subject_ref"])
        for item in expected_bindings
    }
    reports = {
        str(item.get("report_requirement_id") or ""): item
        for item in graph.get("report_requirements") or []
    }
    methods = graph.get("report_method_descriptors") or {}
    items = submitted.get("items")
    if not isinstance(items, list) or (not items and not allow_missing):
        raise ValueError("report_submission.items must be a non-empty array")
    normalized = [
        _item(item, reports=reports, methods=methods)
        for item in items
    ]
    actual = [
        (item["report_requirement_id"], item["subject_ref"])
        for item in normalized
    ]
    if len(actual) != len(set(actual)):
        raise ValueError("report submission bindings must be unique")
    missing = sorted(required - set(actual))
    extra = sorted(set(actual) - required)
    if extra or (missing and not allow_missing):
        raise ValueError(
            "report coverage mismatch: "
            f"missing={_pairs(missing)}; extra={_pairs(extra)}"
        )
    if fragment_hash != report_fragment_hash(normalized):
        raise ValueError("report_submission fragment_hash mismatch")
    value = {
        "schema_version": 1,
        "fragment_hash": fragment_hash,
        "items": sorted(
            normalized,
            key=lambda item: (
                item["report_requirement_id"], item["subject_ref"]
            ),
        ),
    }
    if len(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)) > (
        MAX_REPORT_SUBMISSION_BYTES
    ):
        raise ValueError(
            f"report_submission exceeds {MAX_REPORT_SUBMISSION_BYTES} bytes"
        )
    return value


def expected_report_bindings(
    *,
    graph: dict[str, Any],
    source_node: dict[str, Any],
    edge: dict[str, Any],
    target_node: dict[str, Any],
    entry_assessments: list[dict[str, Any]],
    transition_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the exact dynamic report contract without accepting content."""
    policy = graph.get("report_policy") or {}
    if policy.get("enforcement") != "required":
        return []
    reports = {
        str(item.get("report_requirement_id") or ""): item
        for item in graph.get("report_requirements") or []
    }
    methods = graph.get("report_method_descriptors") or {}
    values = []
    for report_id, subject_ref in sorted(_required_subjects(
        graph=graph,
        source_node=source_node,
        edge=edge,
        target_node=target_node,
        entry_assessments=entry_assessments,
        transition_evidence=transition_evidence,
    )):
        report = reports.get(report_id)
        if report is None:
            raise ValueError(f"unknown report requirement: {report_id}")
        subject_kind = str(
            (report.get("subject_selector") or {}).get("kind") or ""
        )
        prefixes = _SUBJECT_PREFIXES.get(subject_kind)
        if not prefixes or not subject_ref.startswith(prefixes):
            raise ValueError(f"report subject does not match {report_id}")
        method = methods.get(str(report.get("method_ref") or "")) or {}
        allowed = list(method.get("allowed_content") or [])
        if not allowed:
            raise ValueError(
                f"report method has no allowed content: {report_id}"
            )
        values.append({
            "report_requirement_id": report_id,
            "subject_ref": subject_ref,
            "allowed_content": allowed,
        })
    return values


def _required_subjects(
    *, graph: dict[str, Any], source_node: dict[str, Any],
    edge: dict[str, Any], target_node: dict[str, Any],
    entry_assessments: list[dict[str, Any]],
    transition_evidence: dict[str, Any],
) -> set[tuple[str, str]]:
    interrupted = edge.get("edge_type") == "failure"
    required = (
        set()
        if interrupted
        else {
            (str(report_id), f"node:{source_node['node_id']}")
            for report_id in source_node.get("node_report_refs") or []
            if not str(report_id).startswith("report.requirement.")
        }
    )
    required.update(
        (str(report_id), f"graph-edge:{edge['edge_id']}")
        for report_id in edge.get("report_requirement_refs") or []
    )
    required.update(
        (str(report_id), f"node:{target_node['node_id']}")
        for report_id in target_node.get("entry_report_refs") or []
    )
    for report_id in (
        [] if interrupted else source_node.get("node_report_refs") or []
    ):
        report_id = str(report_id)
        if not report_id.startswith("report.requirement."):
            continue
        requirement_id = report_id.removeprefix("report.requirement.")
        # The report proves that the Graph requirement was addressed.  Which
        # research obligations cover that requirement belongs to the entry
        # assessment and obligation-coverage contracts, both of which are
        # validated independently during the same atomic transition.  Making
        # every report item repeat every obligation edge creates a redundant
        # Cartesian product and lets the read-side packet disagree with the
        # write-side gate whenever coverage changes.
        required.add((report_id, f"requirement:{requirement_id}"))
    if (
        edge.get("from_node") == "trial_execution"
        and edge.get("to_node") == "result_audit"
    ):
        evidence_subjects = _evidence_subjects(transition_evidence)
        if not evidence_subjects:
            raise ValueError(
                "evidence admission reporting requires Evidence refs"
            )
        required.update(
            ("report.system.evidence_admission", subject)
            for subject in evidence_subjects
        )
    return required


def _evidence_subjects(value: Any) -> set[str]:
    subjects: set[str] = set()
    if isinstance(value, dict):
        refs = value.get("evidence_refs")
        if isinstance(refs, list):
            subjects.update(
                str(item) for item in refs
                if isinstance(item, str) and item.startswith("evidence:")
            )
        if (
            value.get("schema_version") == 2
            and isinstance(value.get("envelope_id"), str)
            and value.get("envelope_id")
        ):
            subjects.add(f"evidence:{value['envelope_id']}")
        for item in value.values():
            subjects.update(_evidence_subjects(item))
    elif isinstance(value, list):
        for item in value:
            subjects.update(_evidence_subjects(item))
    return subjects


def _item(
    value: Any,
    *,
    reports: dict[str, dict[str, Any]],
    methods: dict[str, dict[str, Any]],
) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "report_requirement_id", "subject_ref", "content_kind", "item_hash",
    }:
        raise ValueError("report submission item fields are invalid")
    report_id = str(value.get("report_requirement_id") or "")
    report = reports.get(report_id)
    if report is None:
        raise ValueError(f"unknown report requirement: {report_id}")
    subject_ref = str(value.get("subject_ref") or "")
    subject_kind = str((report.get("subject_selector") or {}).get("kind") or "")
    prefixes = _SUBJECT_PREFIXES.get(subject_kind)
    if not prefixes or not subject_ref.startswith(prefixes):
        raise ValueError(f"report subject does not match {report_id}")
    content_kind = str(value.get("content_kind") or "")
    method = methods.get(str(report.get("method_ref") or "")) or {}
    if content_kind not in set(method.get("allowed_content") or []):
        raise ValueError(f"report content kind does not match {report_id}")
    return {
        "report_requirement_id": report_id,
        "subject_ref": subject_ref,
        "content_kind": content_kind,
        "item_hash": _hash(value.get("item_hash"), "item_hash"),
    }


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"report_submission.{field} must be sha256")
    return value


def _pairs(values: list[tuple[str, str]]) -> str:
    return ",".join(f"{report_id}@{subject}" for report_id, subject in values)

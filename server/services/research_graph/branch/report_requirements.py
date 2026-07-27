"""Compact report requirements exposed by one active Graph node."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def node_report_requirements(
    *,
    graph: dict[str, Any],
    node: dict[str, Any],
    edges: list[dict[str, Any]],
    report_submission: Any = None,
) -> dict[str, Any]:
    """Return the report contract for the node and its candidate edges.

    The body of a report never crosses this boundary.  Only requirement
    descriptors, subject grammar, allowed content kinds, and hash-only
    coverage status are included in the Agent packet.
    """
    policy = graph.get("report_policy") or {}
    reports = _report_map(graph)
    methods = graph.get("report_method_descriptors") or {}
    nodes = {
        str(item.get("node_id") or ""): item
        for item in graph.get("nodes") or []
        if isinstance(item, dict)
    }
    covered = _covered_items(report_submission)
    current_node = str(node.get("node_id") or "")
    current = {
        "on_entry": _rows(
            reports,
            node.get("entry_report_refs") or [],
            phase="on_entry",
            anchor_ref=f"node:{current_node}",
            covered=covered,
            methods=methods,
        ),
        "on_exit": _rows(
            reports,
            node.get("node_report_refs") or [],
            phase="on_exit",
            anchor_ref=f"node:{current_node}",
            covered=covered,
            methods=methods,
        ),
    }
    edge_values: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        if not edge_id:
            continue
        edge_rows = _rows(
            reports,
            edge.get("report_requirement_refs") or [],
            phase="edge",
            anchor_ref=f"graph-edge:{edge_id}",
            covered=covered,
            methods=methods,
        )
        target = nodes.get(str(edge.get("to_node") or "")) or {}
        target_id = str(target.get("node_id") or "")
        edge_rows.extend(_rows(
            reports,
            target.get("entry_report_refs") or [],
            phase="target_entry",
            anchor_ref=f"node:{target_id}",
            covered=covered,
            methods=methods,
        ))
        edge_values[edge_id] = edge_rows
    return {
        "enforcement": str(policy.get("enforcement") or "optional"),
        "current_node": current,
        "candidate_edges": edge_values,
    }


def compact_report_requirements(value: Any) -> dict[str, Any]:
    """Keep the report contract readable when an Agent packet is bounded."""
    if not isinstance(value, dict):
        return {
            "enforcement": "optional",
            "current_node": {"on_entry": [], "on_exit": []},
            "candidate_edges": {},
        }
    return {
        "enforcement": str(value.get("enforcement") or "optional"),
        "current_node": {
            phase: _compact_rows(rows)
            for phase, rows in (value.get("current_node") or {}).items()
            if phase in {"on_entry", "on_exit"}
        },
        "candidate_edges": {
            str(edge_id): _compact_rows(rows)
            for edge_id, rows in (value.get("candidate_edges") or {}).items()
            if isinstance(rows, list)
        },
    }


def minimal_report_requirements(value: Any) -> dict[str, Any]:
    """Keep only routing fields when the packet is at its byte ceiling."""
    if not isinstance(value, dict):
        return {"enforcement": "optional", "current_node": {}, "candidate_edges": {}}

    def rows(items: Any) -> list[dict[str, Any]]:
        return [
            {
                key: item[key]
                for key in (
                    "report_requirement_id", "status",
                )
                if key in item
            }
            for item in items or []
            if isinstance(item, dict)
        ]

    current = value.get("current_node") or {}
    return {
        "enforcement": str(value.get("enforcement") or "optional"),
        "current_node": {
            key: rows(items)
            for key, items in current.items()
            if key in {"on_entry", "on_exit"}
        },
        "candidate_edges": {},
    }


def _report_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("report_requirement_id") or ""): item
        for item in graph.get("report_requirements") or []
        if isinstance(item, dict) and item.get("report_requirement_id")
    }


def _rows(
    reports: dict[str, dict[str, Any]],
    refs: Any,
    *,
    phase: str,
    anchor_ref: str,
    covered: set[tuple[str, str]],
    methods: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for raw_ref in refs if isinstance(refs, list) else []:
        report_id = str(raw_ref or "")
        report = reports.get(report_id)
        if report is None:
            continue
        subject_ref = _static_subject(report_id, anchor_ref)
        rows.append({
            "report_requirement_id": report_id,
            "title_zh": str(report.get("title_zh") or ""),
            "phase": phase,
            "anchor_kind": str(report.get("anchor_kind") or ""),
            "anchor_ref": str(report.get("anchor_ref") or anchor_ref),
            "subject_selector": deepcopy(
                report.get("subject_selector") or {}
            ),
            "subject_kind": str(
                (report.get("subject_selector") or {}).get("kind") or ""
            ),
            "method_ref": str(report.get("method_ref") or ""),
            "allowed_content": _allowed_content(
                methods=methods, report=report,
            ),
            "slot": str(
                report.get("slot")
                or report.get("document_slot")
                or ""
            ),
            "subject_ref": subject_ref,
            "status": (
                "satisfied" if subject_ref and
                (report_id, subject_ref) in covered else "missing"
            ),
        })
    return rows


def _compact_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [
        {
            key: deepcopy(item.get(key))
            for key in (
                "report_requirement_id", "title_zh", "phase",
                "allowed_content", "slot", "subject_ref", "status",
                "subject_kind",
            )
            if key in item
        }
        for item in rows
        if isinstance(item, dict)
    ]


def _allowed_content(
    *, methods: dict[str, Any], report: dict[str, Any],
) -> list[str]:
    descriptor = methods.get(str(report.get("method_ref") or "")) or {}
    from_method = descriptor.get("allowed_content")
    if isinstance(from_method, list):
        return [str(item) for item in from_method if isinstance(item, str)]
    direct = report.get("allowed_content")
    return [str(item) for item in direct or [] if isinstance(item, str)]


def _static_subject(report_id: str, anchor_ref: str) -> str:
    if report_id.startswith("report.requirement."):
        return ""
    return anchor_ref


def _covered_items(value: Any) -> set[tuple[str, str]]:
    if not isinstance(value, dict):
        return set()
    return {
        (str(item.get("report_requirement_id") or ""),
         str(item.get("subject_ref") or ""))
        for item in value.get("items") or []
        if isinstance(item, dict)
    }
